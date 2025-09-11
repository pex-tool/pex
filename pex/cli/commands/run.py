# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import hashlib
import json
import os.path
import posixpath
import shutil
import sys
import tarfile
from argparse import _ActionsContainer
from contextlib import closing

from pex import dependency_configuration, interpreter
from pex import resolver as pip_resolver
from pex.artifact_url import ArtifactURL, Fingerprint
from pex.atomic_directory import atomic_directory
from pex.build_system import pep_517
from pex.cache import access as cache_access
from pex.cache.dirs import CacheDir
from pex.cli.command import BuildTimeCommand
from pex.cli.commands.cache_aware import CacheAwareMixin
from pex.common import open_zip, safe_copy, safe_mkdtemp, safe_rmtree
from pex.compatibility import shlex_quote
from pex.dist_metadata import (
    DistMetadata,
    Distribution,
    Requirement,
    is_sdist,
    is_tar_sdist,
    is_wheel,
)
from pex.enum import Enum
from pex.exceptions import production_assert, reportable_unexpected_error_msg
from pex.fetcher import URLFetcher
from pex.interpreter import PythonInterpreter
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.os import safe_execv
from pex.pip.version import PipVersionValue
from pex.requirements import LocalProjectRequirement, ParseError, parse_requirement_string
from pex.resolve import lock_resolver, requirement_options, resolver_options, target_options
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.locked_resolve import FileArtifact, UnFingerprintedLocalProjectArtifact
from pex.resolve.lockfile.pep_751 import Dependency, Package, Pylock
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import Resolver, Unsatisfiable
from pex.resolve.script_metadata import apply_script_metadata
from pex.resolve.target_configuration import TargetConfiguration
from pex.result import Error, Result, ResultError, try_
from pex.targets import LocalInterpreter, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV, venv_dir
from pex.venv import installer
from pex.venv.installer import Provenance
from pex.venv.virtualenv import Virtualenv
from pex.wheel import Wheel

if TYPE_CHECKING:
    from typing import Iterable, Iterator, List, Optional, Tuple, Union

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


def _resolve_local_interpreter(
    target_configuration,  # type: TargetConfiguration
    source,  # type: str
):
    # type: (...) -> Union[LocalInterpreter, Error]
    target = try_(
        target_configuration.resolve_targets().require_at_most_one_target(
            "resolving {source}".format(source=source)
        )
    )
    if target is None:
        return LocalInterpreter.create()

    if not isinstance(target, LocalInterpreter):
        return Error(
            "The target configuration options selected a non-local target but only local Python "
            "interpreters can be used by `pex3 run`: {target}".format(
                target=target.render_description()
            )
        )
    return target


_UNSET = object()


class LockedChoice(Enum["LockedChoice.Value"]):
    class Value(Enum.Value):
        pass

    AUTO = Value("auto")
    IGNORE = Value("ignore")
    REQUIRE = Value("require")


LockedChoice.seal()


@attr.s(frozen=True)
class RunSpec(object):
    target_configuration = attr.ib()  # type: TargetConfiguration
    target = attr.ib()  # type: LocalInterpreter
    entry_point = attr.ib()  # type: str
    is_script = attr.ib()  # type: bool
    pip_configuration = attr.ib()  # type: PipConfiguration
    run_requirement = attr.ib(default=None)  # type: Optional[Requirement]
    all_requirements = attr.ib(default=RequirementConfiguration())  # type: RequirementConfiguration
    args = attr.ib(default=())  # type: Tuple[str, ...]
    locks = attr.ib(default=())  # type: Tuple[str, ...]
    locked_choice = attr.ib(default=LockedChoice.AUTO)  # type: LockedChoice.Value

    def fingerprint(self, network_configuration):
        # type: (NetworkConfiguration) -> str

        return hashlib.sha1(
            json.dumps(
                {
                    "requirements": sorted(
                        (
                            str(req)
                            for req in self.all_requirements.parse_requirements(
                                network_configuration=network_configuration
                            )
                        )
                    ),
                    "constraints": sorted(
                        (
                            str(req)
                            for req in self.all_requirements.parse_constraints(
                                network_configuration=network_configuration
                            )
                        )
                    ),
                    "target": {
                        "markers": self.target.marker_environment.as_dict(),
                        "tag": str(self.target.supported_tags[0]),
                    },
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def calculate_entry_point(self, venv):
        # type: (Virtualenv) -> EntryPoint

        if self.is_script:
            script_relpath = os.path.basename(self.entry_point)
            script_abspath = os.path.join(venv.venv_dir, script_relpath)
            if not os.path.exists(script_abspath):
                safe_copy(self.entry_point, script_abspath)
            return EntryPoint(type=EntryPointType.SCRIPT, value=script_relpath)

        console_script = venv.bin_path(self.entry_point)
        if os.path.isfile(console_script):
            script_relpath = os.path.relpath(console_script, venv.venv_dir)
            return EntryPoint(type=EntryPointType.CONSOLE_SCRIPT, value=script_relpath)

        return EntryPoint(type=EntryPointType.MODULE, value=self.entry_point)


def _create_sdist(
    local_project,  # type: LocalProjectRequirement
    dist_dir,  # type: str
    target,  # type: LocalInterpreter
    resolver,  # type: Resolver
    pip_version,  # type: PipVersionValue
):
    # type: (...) -> Tuple[LocalProjectRequirement, str]

    sdist = try_(
        pep_517.build_sdist(
            project_directory=local_project.path,
            dist_dir=dist_dir,
            target=target,
            resolver=resolver,
            pip_version=pip_version,
        )
    )
    return local_project, sdist


def _create_sdists(
    projects,  # type: Iterable[LocalProjectRequirement]
    target,  # type: LocalInterpreter
    pip_configuration,  # type: PipConfiguration
    refresh=False,  # type: bool
):
    # type: (...) -> Iterator[Tuple[LocalProjectRequirement, str]]

    # TODO(John Sirois): Parallelize.
    for local_project in projects:
        dist_dir = CacheDir.RUN.path(
            "local-projects", hashlib.sha1(local_project.path.encode("utf-8")).hexdigest()
        )

        if refresh:
            safe_rmtree(dist_dir)
        with atomic_directory(dist_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                try_(
                    pep_517.build_sdist(
                        project_directory=local_project.path,
                        dist_dir=dist_dir,
                        target=target,
                        resolver=ConfiguredResolver(pip_configuration),
                        pip_version=pip_configuration.version,
                    )
                )

        sdists = glob.glob(os.path.join(dist_dir, "*.tar.gz"))
        production_assert(
            len(sdists) == 1,
            "Expected build of {path} to produce 1 sdist, found: {sdists}",
            path=local_project.path,
            sdists=", ".join(sdists),
        )
        yield local_project, sdists[0]


@attr.s(frozen=True)
class RunConfig(object):
    entry_point = attr.ib(default=None)  # type: Union[str, LocalProjectRequirement, Script]
    requirement = attr.ib(default=None)  # type: Optional[ParsedRequirement]
    extra_requirements = attr.ib(
        default=RequirementConfiguration()
    )  # type: RequirementConfiguration
    args = attr.ib(default=())  # type: Tuple[str, ...]
    locks = attr.ib(default=())  # type: Tuple[str, ...]
    locked_choice = attr.ib(default=LockedChoice.AUTO)  # type: LockedChoice.Value

    def resolve_run_spec(
        self,
        target_configuration,  # type: TargetConfiguration
        target,  # type: LocalInterpreter
        pip_configuration,  # type: PipConfiguration
        refresh=False,  # type: bool
    ):
        # type: (...) -> RunSpec

        requirement = None  # type: Optional[Requirement]
        extra_requirements = OrderedSet()  # type: OrderedSet[Requirement]
        local_projects = OrderedSet()  # type: OrderedSet[LocalProjectRequirement]

        entry_point = None  # type: Optional[str]
        is_script = False
        if isinstance(self.entry_point, str):
            entry_point = self.entry_point
        elif isinstance(self.entry_point, LocalProjectRequirement):
            local_projects.add(self.entry_point)
        else:  # Script
            entry_point, script_reqs, target = try_(
                self.entry_point.resolve(
                    target_configuration,
                    target,
                    pip_configuration,
                    refresh=refresh,
                    locked_choice=self.locked_choice,
                )
            )
            is_script = True
            extra_requirements.update(script_reqs)

        if isinstance(self.requirement, LocalProjectRequirement):
            local_projects.add(self.requirement)
        elif self.requirement:
            requirement = self.requirement.requirement

        local_project_to_sdist = dict(
            _create_sdists(
                projects=local_projects,
                target=target,
                pip_configuration=pip_configuration,
                refresh=refresh,
            )
        )

        for local_project, sdist in local_project_to_sdist.items():
            project_name = DistMetadata.load(sdist).project_name
            local_project_req = Requirement.local(project_name=project_name, path=sdist)
            if self.entry_point == local_project:
                entry_point = project_name.raw
                requirement = local_project_req
            else:
                extra_requirements.add(local_project_req)

        if entry_point is None:
            raise AssertionError(
                reportable_unexpected_error_msg(
                    "Failed to calculate and entry point from: {self}", self=self
                )
            )

        locks = []  # type: List[str]
        if self.locked_choice is not LockedChoice.IGNORE:
            if isinstance(self.entry_point, Script):
                name, _ = os.path.splitext(os.path.basename(entry_point))
            else:
                name = entry_point
            locks.append("pylock.{name}.toml".format(name=name))
            locks.append("pylock.toml")

        requirements = OrderedSet()  # type: OrderedSet[str]
        if requirement:
            requirements.add(str(requirement))
        requirements.update(map(str, extra_requirements))
        if self.extra_requirements.requirements:
            requirements.update(self.extra_requirements.requirements)

        return RunSpec(
            target_configuration=target_configuration,
            target=target,
            entry_point=entry_point,
            is_script=is_script,
            pip_configuration=pip_configuration,
            run_requirement=requirement,
            all_requirements=attr.evolve(self.extra_requirements, requirements=requirements),
            args=self.args,
            locks=tuple(locks),
            locked_choice=self.locked_choice,
        )


@attr.s(frozen=True)
class Script(object):
    url = attr.ib()  # type: ArtifactURL

    def _resolve_lock(
        self,
        fetcher,  # type: URLFetcher
        download_dir,  # type: str
        lock_name,  # type: str
    ):
        # type: (...) -> bool

        lock_url = ArtifactURL.from_url_info(
            self.url.url_info._replace(
                path=posixpath.join(posixpath.dirname(self.url.path), lock_name)
            )
        )
        try:
            with fetcher.get_body_stream(lock_url.download_url) as src_fp, open(
                os.path.join(download_dir, lock_name), "wb"
            ) as dst_fp:
                shutil.copyfileobj(src_fp, dst_fp)
        except (IOError, OSError):
            return False
        else:
            return True

    def _resolve_script(
        self,
        pip_configuration,  # type: PipConfiguration
        refresh=False,  # type: bool
        locked_choice=LockedChoice.AUTO,  # type: LockedChoice.Value
    ):
        # type: (...) -> Union[str, Error]

        if "file" == self.url.scheme:
            if not os.path.exists(self.url.path):
                return Error(
                    "The path {path} pointed at by {entry_point} does not exist.".format(
                        path=self.url.path, entry_point=self.url
                    )
                )
            return self.url.path

        download_url = self.url.download_url
        cache_dir = CacheDir.RUN.path(
            "scripts", hashlib.sha1(download_url.encode("utf-8")).hexdigest()
        )
        script_name = posixpath.basename(self.url.path)

        if refresh:
            safe_rmtree(cache_dir)
        with atomic_directory(cache_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                fetcher = URLFetcher(
                    network_configuration=pip_configuration.network_configuration,
                    password_entries=pip_configuration.repos_configuration.password_entries,
                )
                with fetcher.get_body_stream(download_url) as src_fp, open(
                    os.path.join(atomic_dir.work_dir, script_name), "wb"
                ) as dst_fp:
                    shutil.copyfileobj(src_fp, dst_fp)
                if locked_choice is not LockedChoice.IGNORE:
                    name, _ = os.path.splitext(script_name)
                    for lock in "pylock.{name}.toml".format(name=name), "pylock.toml":
                        if self._resolve_lock(fetcher, atomic_dir.work_dir, lock):
                            break
        return os.path.join(cache_dir, script_name)

    def resolve(
        self,
        target_configuration,  # type: TargetConfiguration
        target,  # type: LocalInterpreter
        pip_configuration,  # type: PipConfiguration
        refresh=False,  # type: bool
        locked_choice=LockedChoice.AUTO,  # type: LockedChoice.Value
    ):
        # type: (...) -> Union[Tuple[str, Iterable[Requirement], LocalInterpreter], Error]

        script = try_(
            self._resolve_script(pip_configuration, refresh=refresh, locked_choice=locked_choice)
        )
        try:
            script_metadata_application = apply_script_metadata(
                scripts=[script],
                requirement_configuration=RequirementConfiguration(),
                target_configuration=target_configuration,
            )
        except Unsatisfiable as e:
            return Error(str(e))

        requirements = OrderedSet()  # type: OrderedSet[Requirement]
        if script_metadata_application.target_does_not_apply(target):
            target = try_(_resolve_local_interpreter(target_configuration, script))
        if script_metadata_application.requirement_configuration.requirements:
            requirements.update(
                Requirement.parse(req)
                for req in script_metadata_application.requirement_configuration.requirements
            )

        return script, requirements, target


class EntryPointType(Enum["EntryPointType.Value"]):
    class Value(Enum.Value):
        pass

    CONSOLE_SCRIPT = Value("console-script")
    MODULE = Value("module")
    SCRIPT = Value("script")


EntryPointType.seal()


@attr.s(frozen=True)
class EntryPoint(object):
    type = attr.ib()  # type: EntryPointType.Value
    value = attr.ib()  # type: str

    def command(
        self,
        venv,  # type: Virtualenv
        *args  # type: str
    ):
        # type: (...) -> List[str]

        if self.type is EntryPointType.CONSOLE_SCRIPT:
            command = [os.path.join(venv.venv_dir, self.value)]
        elif self.type is EntryPointType.SCRIPT:
            command = [venv.interpreter.binary, os.path.join(venv.venv_dir, self.value)]
        else:
            command = [venv.interpreter.binary, "-m", self.value]
        command.extend(args)
        return command


class Run(CacheAwareMixin, BuildTimeCommand):
    """Run a tool."""

    @classmethod
    def supports_unknown_args(cls):
        return True

    @classmethod
    def add_extra_arguments(cls, parser):
        # type: (_ActionsContainer) -> None

        parser.add_argument(
            "--from",
            "--spec",
            dest="requirement",
            metavar="REQUIREMENT",
            type=str,
            default=None,
            help=(
                "The requirement of the tool to run. Only needed if the entry point does not "
                "correspond to the name of the project providing the entry point or if a specific "
                "version of the project is required."
            ),
        )
        parser.add_argument(
            "--with",
            dest="extra_requirements",
            metavar="REQUIREMENTS",
            type=str,
            default=[],
            action="append",
            help="Extra requirements to run the tool with.",
        )
        parser.add_argument(
            "--locked",
            choices=LockedChoice.values(),
            type=LockedChoice.for_value,
            default=LockedChoice.AUTO,
            help=(
                "Whether to resolve the tool to run respecting the PEP-751 lock file it ships "
                "with, if any. By default the search order is for `pylock.<entry point>.toml` "
                "first and then `pylock.toml` if the entry-point-specific lock file is not found. "
                "If the project is distributed as a wheel, the lock file is looked for in the "
                "`pylock` dist-info sub-directory. If the project is a source distribution the "
                "lock file is looked for in the source distribution root directory respecting "
                "#subdirectory= if used in the project `--requirement`. If no lock file is found, "
                "the tool transitive dependencies are resolved as per --requirement if supplied; "
                "otherwise the latest compatible version and its latest compatible transitive "
                "dependencies are resolved. To skip looking at tool lock files, specify "
                "`--locked {ignore}` and to require a lock file be found and used specify "
                "`--locked {require}`.".format(
                    ignore=LockedChoice.IGNORE.value, require=LockedChoice.REQUIRE.value
                )
            ),
        )
        parser.add_argument(
            "--refresh",
            dest="refresh",
            action="store_true",
            help="Refresh the cached tool venv, if cached.",
        )
        parser.add_argument(
            "entry_point",
            nargs=1,
            help=(
                "The entry point of the tool to run. If no `--req` is supplied, the entry point is "
                "assumed to be the name of the project to resolve as well as the name of an entry "
                "point the project provides."
            ),
        )
        requirement_options.register(parser, include_positional_requirements=False)
        target_options.register(
            parser.add_argument_group("Target python options"), include_platforms=False
        )
        resolver_options.register(parser.add_argument_group("Resolver options"))
        dependency_configuration.register(parser.add_argument_group("Dependency options"))

    def _parse_options(self, raw_entry_point):
        # type: (str) -> Union[RunConfig, Error]

        requirement_configuration = requirement_options.configure(
            self.options, self.options.extra_requirements
        )
        entry_point = raw_entry_point  # type: Union[str, LocalProjectRequirement, Script]
        requirement = None  # type: Optional[ParsedRequirement]
        if self.options.requirement:
            try:
                requirement = parse_requirement_string(self.options.requirement)
            except ParseError as e:
                return Error(
                    "Invalid --from requirement {requirement}: {err}".format(
                        requirement=self.options.requirement, err=e
                    )
                )

        try:
            entry_point_req = parse_requirement_string(raw_entry_point)
        except ParseError:
            try:
                entry_point = Script(ArtifactURL.parse(raw_entry_point))
            except ValueError as e:
                return Error(
                    "Invalid entry point {entry_point!r}. It is neither a valid requirement "
                    "nor a local or remote script: {err}".format(entry_point=entry_point, err=e)
                )
        else:
            if requirement is None:
                requirement = entry_point_req
            if isinstance(entry_point_req, LocalProjectRequirement):
                entry_point = entry_point_req
            else:
                entry_point = entry_point_req.requirement.project_name.raw

        return RunConfig(
            entry_point=entry_point,
            requirement=requirement,
            extra_requirements=requirement_configuration,
            args=self.passthrough_args or (),
            locked_choice=self.options.locked,
        )

    def _resolve_pylock(self, run_spec):
        # type: (RunSpec) -> Union[Optional[Tuple[Optional[Package], str]], Error]

        if run_spec.is_script:
            for lock_name in run_spec.locks:
                lock_path = os.path.join(os.path.dirname(run_spec.entry_point), lock_name)
                if os.path.isfile(lock_path):
                    return None, lock_path
            return None

        requirement = run_spec.run_requirement
        if requirement is None:
            return None

        pip_configuration = run_spec.pip_configuration
        resolver = ConfiguredResolver(pip_configuration=pip_configuration)
        targets = Targets.from_target(run_spec.target)
        dep_config = dependency_configuration.configure(self.options)

        downloaded = pip_resolver.download(
            targets=targets,
            requirements=[str(requirement)],
            constraint_files=run_spec.all_requirements.constraint_files,
            allow_prereleases=pip_configuration.allow_prereleases,
            transitive=False,
            repos_configuration=pip_configuration.repos_configuration,
            resolver_version=pip_configuration.resolver_version,
            network_configuration=pip_configuration.network_configuration,
            build_configuration=pip_configuration.build_configuration,
            max_parallel_jobs=pip_configuration.max_jobs,
            pip_log=pip_configuration.log,
            pip_version=pip_configuration.version,
            resolver=resolver,
            use_pip_config=pip_configuration.use_pip_config,
            extra_pip_requirements=pip_configuration.extra_requirements,
            keyring_provider=pip_configuration.keyring_provider,
            dependency_configuration=dep_config,
        )
        production_assert(
            len(downloaded.local_distributions) == 1,
            "Expected to download exactly 1 distribution for {requirement}, found {count}:\n"
            "{dists}",
            requirement=requirement,
            count=len(downloaded.local_distributions),
            dists="\n".join(ld.path for ld in downloaded.local_distributions),
        )
        distribution = downloaded.local_distributions[0]

        dist_metadata = DistMetadata.load(distribution.path)
        package = Package(
            index=-1,
            project_name=dist_metadata.project_name,
            artifact=FileArtifact(
                url=ArtifactURL.parse("file://{path}".format(path=distribution.path)),
                verified=True,
                fingerprint=Fingerprint(algorithm="sha256", hash=distribution.fingerprint),
                filename=os.path.basename(distribution.path),
            ),
            artifact_is_archive=True,
            version=dist_metadata.version,
            requires_python=dist_metadata.requires_python,
        )

        lock_dest_dir = safe_mkdtemp(
            prefix="pex3-run.",
            suffix=".{project_name}-locked".format(project_name=dist_metadata.project_name),
        )
        if is_wheel(distribution.path):
            wheel = Wheel.load(distribution.path)
            with open_zip(distribution.path) as zf:
                names = frozenset(zf.namelist())
                for lock_name in run_spec.locks:
                    lock_path = "{metadata_dir}/pylock/{lock_name}".format(
                        metadata_dir=wheel.metadata_dir, lock_name=lock_name
                    )
                    if lock_path in names:
                        zf.extract(lock_path, lock_dest_dir)
                        TRACER.log(
                            "Using lock in {wheel} at {path}.".format(
                                wheel=os.path.basename(distribution.path), path=lock_path
                            )
                        )
                        return package, os.path.join(lock_dest_dir, lock_path)
        elif is_sdist(distribution.path):
            if is_tar_sdist(distribution.path):
                with closing(tarfile.open(distribution.path)) as tf:
                    tf.extractall(lock_dest_dir)
            else:
                with open_zip(distribution.path) as zf:
                    zf.extractall(lock_dest_dir)
            entries = glob.glob(os.path.join(lock_dest_dir, "*"))
            if len(entries) != 1:
                return Error(
                    "Expected {sdist} to have 1 entry, found {count}: {entries}".format(
                        sdist=distribution.path, count=len(entries), entries=entries
                    )
                )
            sdist_root = entries[0]
            for lock_name in run_spec.locks:
                lock_path = os.path.join(sdist_root, lock_name)
                if os.path.exists(lock_path):
                    TRACER.log(
                        "Using lock in {sdist} at {path}.".format(
                            sdist=os.path.basename(distribution.path),
                            path=os.path.relpath(lock_path, lock_dest_dir),
                        )
                    )
                    return package, lock_path

        TRACER.log("No lock found in {dist}.".format(dist=os.path.basename(distribution.path)))
        return None

    def _resolve_tool(
        self,
        run_spec,  # type: RunSpec
        pylock=None,  # type: Optional[Pylock]
    ):
        # type: (...) -> Union[Tuple[Distribution, ...], Error]

        pip_configuration = run_spec.pip_configuration
        resolver = ConfiguredResolver(pip_configuration=pip_configuration)
        targets = Targets.from_target(run_spec.target)
        dep_config = dependency_configuration.configure(self.options)
        if pylock:
            resolved = lock_resolver.resolve_from_pylock(
                targets=targets,
                pylock=pylock,
                resolver=resolver,
                requirements=run_spec.all_requirements.requirements,
                requirement_files=run_spec.all_requirements.requirement_files,
                constraint_files=run_spec.all_requirements.constraint_files,
                repos_configuration=pip_configuration.repos_configuration,
                resolver_version=pip_configuration.resolver_version,
                network_configuration=pip_configuration.network_configuration,
                build_configuration=pip_configuration.build_configuration,
                transitive=pip_configuration.transitive,
                max_parallel_jobs=pip_configuration.max_jobs,
                pip_version=pip_configuration.version,
                use_pip_config=pip_configuration.use_pip_config,
                extra_pip_requirements=pip_configuration.extra_requirements,
                keyring_provider=pip_configuration.keyring_provider,
                dependency_configuration=dep_config,
            )
        else:
            resolved = pip_resolver.resolve(
                targets=targets,
                requirements=run_spec.all_requirements.requirements,
                requirement_files=run_spec.all_requirements.requirement_files,
                constraint_files=run_spec.all_requirements.constraint_files,
                allow_prereleases=pip_configuration.allow_prereleases,
                transitive=pip_configuration.transitive,
                repos_configuration=pip_configuration.repos_configuration,
                resolver_version=pip_configuration.resolver_version,
                network_configuration=pip_configuration.network_configuration,
                build_configuration=pip_configuration.build_configuration,
                max_parallel_jobs=pip_configuration.max_jobs,
                pip_log=pip_configuration.log,
                pip_version=pip_configuration.version,
                resolver=resolver,
                use_pip_config=pip_configuration.use_pip_config,
                extra_pip_requirements=pip_configuration.extra_requirements,
                keyring_provider=pip_configuration.keyring_provider,
                dependency_configuration=dep_config,
            )
        if isinstance(resolved, Error):
            return resolved
        return tuple(resolved_dist.distribution for resolved_dist in resolved.distributions)

    def _ensure_tool_venv(
        self,
        tool_venv_dir,  # type: str
        run_spec,  # type: RunSpec
    ):
        # type: (...) -> List[str]

        with atomic_directory(tool_venv_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                pylock = None  # type: Optional[Pylock]
                if run_spec.locks:
                    maybe_lock = try_(self._resolve_pylock(run_spec))
                    if not maybe_lock and run_spec.locked_choice is LockedChoice.REQUIRE:
                        raise ResultError(
                            Error("A tool lock file was required but none was found.")
                        )
                    if maybe_lock:
                        package, lock_path = maybe_lock
                        pylock = try_(Pylock.parse(lock_path))
                        packages = list(pylock.packages)
                        local_project_requirement_mapping = {}
                        if package:
                            packages.append(
                                attr.evolve(
                                    package,
                                    index=len(packages),
                                    dependencies=tuple(
                                        # N.B.: The root tool package does not necessarily depend on all
                                        # other packages in the lock, but it is harmless to claim this
                                        # to ensure a full tool + lock install.
                                        Dependency(package.index, package.project_name)
                                        for package in packages
                                    ),
                                )
                            )
                            if isinstance(package.artifact, UnFingerprintedLocalProjectArtifact):
                                local_project_requirement_mapping[
                                    package.artifact.directory
                                ] = package.as_requirement()

                        pylock = attr.evolve(
                            pylock,
                            packages=tuple(packages),
                            local_project_requirement_mapping=local_project_requirement_mapping,
                        )

                distributions = try_(self._resolve_tool(run_spec, pylock=pylock))
                with interpreter.path_mapping(atomic_dir.work_dir, tool_venv_dir):
                    venv = Virtualenv.create_atomic(
                        venv_dir=atomic_dir,
                        interpreter=PythonInterpreter.get(),
                    )
                    provenance = Provenance.create(
                        venv=venv, python=interpreter.adjust_to_final_path(venv.interpreter.binary)
                    )
                    installer.populate_venv_distributions(
                        venv=venv, distributions=distributions, provenance=provenance
                    )

        venv = Virtualenv(tool_venv_dir)
        entry_point = run_spec.calculate_entry_point(venv)
        return entry_point.command(venv, *run_spec.args)

    def run(self):
        # type: () -> Result

        entry_point = self.options.entry_point[0]
        run_config = try_(self._parse_options(entry_point))

        target_configuration = TargetConfiguration(
            interpreter_configuration=target_options.configure_interpreters(self.options)
        )
        target = try_(_resolve_local_interpreter(target_configuration, source=entry_point))

        pip_configuration = resolver_options.create_pip_configuration(self.options)
        refresh = self.options.refresh

        cache_access.read_write()
        if refresh:
            if not self.lock_cache_for_delete(out=sys.stderr):
                return Error("Failed to lock Pex cache for refresh.")

        run_spec = run_config.resolve_run_spec(
            target_configuration, target, pip_configuration, refresh=refresh
        )

        tool_venv_dir = venv_dir(
            pex_root=ENV.PEX_ROOT,
            pex_hash=run_spec.fingerprint(
                network_configuration=pip_configuration.network_configuration
            ),
            has_interpreter_constraints=False,
        )

        if refresh:
            safe_rmtree(tool_venv_dir.path)

        command = self._ensure_tool_venv(tool_venv_dir.path, run_spec)
        cache_access.record_access(tool_venv_dir)

        TRACER.log(
            "Running: {command}".format(command=" ".join(shlex_quote(arg) for arg in command))
        )
        safe_execv(command)
