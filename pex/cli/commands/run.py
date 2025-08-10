# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import hashlib
import json
import os.path
import shutil
import tarfile
from argparse import _ActionsContainer
from contextlib import closing

from pex import dependency_configuration, interpreter
from pex import resolver as pip_resolver
from pex.artifact_url import ArtifactURL, Fingerprint
from pex.atomic_directory import atomic_directory
from pex.build_system import pep_517
from pex.cache import access as cache_access
from pex.cli.command import BuildTimeCommand
from pex.common import open_zip, safe_copy, safe_mkdtemp, safe_rmtree
from pex.compatibility import shlex_quote
from pex.dist_metadata import DistMetadata, Distribution, is_sdist, is_tar_sdist, is_wheel
from pex.enum import Enum
from pex.exceptions import production_assert
from pex.fetcher import URLFetcher
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.os import safe_execv
from pex.requirements import LocalProjectRequirement, ParseError, parse_requirement_string
from pex.resolve import lock_resolver, resolver_options, target_options
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.locked_resolve import FileArtifact, UnFingerprintedLocalProjectArtifact
from pex.resolve.lockfile.pep_751 import Dependency, Package, Pylock
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import Unsatisfiable
from pex.resolve.script_metadata import apply_script_metadata
from pex.resolve.target_configuration import TargetConfiguration
from pex.resolver import LocalDistribution
from pex.result import Error, Result, ResultError, try_
from pex.targets import LocalInterpreter, Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper
from pex.variables import ENV, venv_dir
from pex.venv import installer
from pex.venv.installer import Provenance
from pex.venv.virtualenv import Virtualenv
from pex.wheel import Wheel

if TYPE_CHECKING:
    from typing import Iterable, List, Optional, Tuple, Union

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement
else:
    from pex.third_party import attr


_UNSET = object()


class LockedChoice(Enum["LockedChoice.Value"]):
    class Value(Enum.Value):
        pass

    AUTO = Value("auto")
    IGNORE = Value("ignore")
    REQUIRE = Value("require")


LockedChoice.seal()


@attr.s(frozen=True)
class RunConfig(object):
    entry_point = attr.ib()  # type: Union[str, ArtifactURL]
    requirement = attr.ib(default=None)  # type: Optional[ParsedRequirement]
    requirement_is_entry_point = attr.ib(default=False)  # type: bool
    args = attr.ib(default=())  # type: Tuple[str, ...]
    locks = attr.ib(default=())  # type: Tuple[str, ...]
    locked_choice = attr.ib(default=LockedChoice.AUTO)  # type: LockedChoice.Value

    def fingerprint(self, target):
        # type: (Target) -> str

        return hashlib.sha1(
            json.dumps(
                {
                    "requirement": str(self.requirement) if self.requirement else self.entry_point,
                    "target": {
                        "markers": target.marker_environment.as_dict(),
                        "tag": str(target.platform.supported_tags[0]),
                    },
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()


@attr.s(frozen=True)
class ToolResolve(object):
    run_distribution = attr.ib(default=None)  # type: Optional[Distribution]
    distributions = attr.ib(default=())  # type: Tuple[Distribution, ...]
    script = attr.ib(default=None)  # type: Optional[str]


class EntryPointType(Enum["EntryPointType.Value"]):
    class Value(Enum.Value):
        pass

    CONSOLE_SCRIPT = Value("console-script")
    MODULE = Value("module")
    SCRIPT = Value("script")


EntryPointType.seal()


@attr.s(frozen=True)
class EntryPoint(object):
    @classmethod
    def load(cls, tool_venv_dir):
        # type: (str) -> Union[EntryPoint, Error]

        entry_point_file = os.path.join(tool_venv_dir, "ENTRY-POINT")
        try:
            with open(entry_point_file) as fp:
                entry_point_data = json.load(fp)
        except (IOError, OSError, ValueError) as e:
            return Error(str(e))

        if not isinstance(entry_point_data, dict):
            return Error(
                "The entry point file at {path} has an unexpected schema.".format(
                    path=entry_point_file
                )
            )

        ep_type = entry_point_data.pop("type", None)
        ep_value = entry_point_data.pop("value", None)
        if entry_point_data or not isinstance(ep_type, str) or not isinstance(ep_value, str):
            return Error(
                "The entry point file at {path} has an unexpected schema.".format(
                    path=entry_point_file
                )
            )

        try:
            return cls(type=EntryPointType.for_value(ep_type), value=ep_value)
        except ValueError as e:
            return Error(str(e))

    type = attr.ib()  # type: EntryPointType.Value
    value = attr.ib()  # type: str

    def store(self, tool_venv_dir):
        # type: (str) -> None
        with open(os.path.join(tool_venv_dir, "ENTRY-POINT"), "w") as fp:
            json.dump({"type": self.type.value, "value": self.value}, fp)

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


class Run(BuildTimeCommand):
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
            "--requirement",
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
        target_options.register(
            parser.add_argument_group("Target python options"), include_platforms=False
        )
        resolver_options.register(parser.add_argument_group("Resolver options"))
        dependency_configuration.register(parser.add_argument_group("Dependency options"))

    def _parse_options(self):
        # type: () -> Union[RunConfig, Error]

        entry_point = self.options.entry_point[0]

        requirement = None  # type: Optional[ParsedRequirement]
        requirement_is_entry_point = False
        if self.options.requirement:
            try:
                requirement = parse_requirement_string(self.options.requirement)
            except ParseError as e:
                return Error(
                    "Invalid requirement {requirement}: {err}".format(
                        requirement=self.options.requirement, err=e
                    )
                )
            script = ArtifactURL.parse(entry_point)
            if script.scheme != "file" or os.path.isfile(script.path):
                entry_point = script
        else:
            try:
                requirement = parse_requirement_string(entry_point)
            except ParseError:
                try:
                    entry_point = ArtifactURL.parse(entry_point)
                except ValueError as e:
                    return Error(
                        "Invalid entry point {entry_point!r}. It is neither a valid requirement "
                        "nor a local or remote script: {err}".format(entry_point=entry_point, err=e)
                    )
            else:
                requirement_is_entry_point = True

        locks = []  # type: List[str]
        if self.options.locked is not LockedChoice.IGNORE:
            locks.append("pylock.{entry_point}.toml".format(entry_point=entry_point))
            locks.append("pylock.toml")

        return RunConfig(
            entry_point=entry_point,
            requirement=requirement,
            requirement_is_entry_point=requirement_is_entry_point,
            args=self.passthrough_args or (),
            locks=tuple(locks),
            locked_choice=self.options.locked,
        )

    def _resolve_pylock(
        self,
        target,  # type: Target
        requirement,  # type: ParsedRequirement
        lock_names,  # type: Iterable[str]
    ):
        # type: (...) -> Union[Tuple[Package, Optional[str]], Error]

        pip_configuration = resolver_options.create_pip_configuration(self.options)
        resolver = ConfiguredResolver(pip_configuration=pip_configuration)
        targets = Targets.from_target(target)
        dep_config = dependency_configuration.configure(self.options)

        downloaded = pip_resolver.download(
            targets=targets,
            requirements=[str(requirement)],
            allow_prereleases=pip_configuration.allow_prereleases,
            transitive=False,
            indexes=pip_configuration.repos_configuration.indexes,
            find_links=pip_configuration.repos_configuration.find_links,
            resolver_version=pip_configuration.resolver_version,
            network_configuration=pip_configuration.network_configuration,
            password_entries=pip_configuration.repos_configuration.password_entries,
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

        artifact_url = ArtifactURL.parse("file://{path}".format(path=distribution.path))
        if os.path.isdir(distribution.path):
            production_assert(
                isinstance(requirement, LocalProjectRequirement),
                "Expected {requirement} to be a {expected} but is a {actual}.",
                requirement=requirement,
                expected=LocalProjectRequirement.__name__,
                actual=type(requirement).__name__,
            )
            project_directory = distribution.path
            sdist = try_(
                pep_517.build_sdist(
                    distribution.path,
                    dist_dir=safe_mkdtemp(prefix="pex3-run.", suffix=".build-sdist"),
                    target=target,
                    resolver=resolver,
                    pip_version=pip_configuration.version,
                )
            )
            distribution = LocalDistribution(
                path=sdist, fingerprint=CacheHelper.hash(sdist, hasher=hashlib.sha256)
            )
            artifact = UnFingerprintedLocalProjectArtifact(
                url=artifact_url,
                verified=True,
                directory=project_directory,
                # N.B.: MyPy can't see our production_assert above.
                editable=cast(LocalProjectRequirement, requirement).editable,
            )  # type: Union[UnFingerprintedLocalProjectArtifact, FileArtifact]
        else:
            artifact = FileArtifact(
                url=artifact_url,
                verified=True,
                fingerprint=Fingerprint(algorithm="sha256", hash=distribution.fingerprint),
                filename=os.path.basename(distribution.path),
            )

        dist_metadata = DistMetadata.load(distribution.path)

        package = Package(
            index=-1,
            project_name=dist_metadata.project_name,
            artifact=artifact,
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
                for lock_name in lock_names:
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
            for lock_name in lock_names:
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
        return package, None

    @staticmethod
    def _resolve_script(
        url,  # type: ArtifactURL
        pip_configuration,  # type: PipConfiguration
    ):
        # type: (...) -> Union[str, Error]

        if "file" == url.scheme:
            if not os.path.exists(url.path):
                return Error(
                    "The path {path} pointed at by {entry_point} does not exist.".format(
                        path=url.path, entry_point=url
                    )
                )
            return url.path

        fetcher = URLFetcher(
            network_configuration=pip_configuration.network_configuration,
            password_entries=pip_configuration.repos_configuration.password_entries,
        )
        with fetcher.get_body_stream(url.download_url) as src_fp, open(
            os.path.join(
                safe_mkdtemp(prefix="pex3-run.", suffix=".remote-script"),
                os.path.basename(url.path),
            ),
            "wb",
        ) as dst_fp:
            shutil.copyfileobj(src_fp, dst_fp)
        return dst_fp.name

    def _resolve_tool(
        self,
        target_configuration,  # type: TargetConfiguration
        target,  # type: Target
        run_config,  # type: RunConfig
        pylock=None,  # type: Optional[Pylock]
    ):
        # type: (...) -> Union[ToolResolve, Error]

        pip_configuration = resolver_options.create_pip_configuration(self.options)
        resolver = ConfiguredResolver(pip_configuration=pip_configuration)
        targets = Targets.from_target(target)
        dep_config = dependency_configuration.configure(self.options)

        script = None  # type: Optional[str]
        requirements = OrderedSet()  # type: OrderedSet[str]
        if run_config.requirement:
            requirements.add(str(run_config.requirement))

        if isinstance(run_config.entry_point, ArtifactURL):
            script = try_(
                self._resolve_script(
                    url=run_config.entry_point, pip_configuration=pip_configuration
                )
            )
            try:
                script_metadata_application = apply_script_metadata(
                    scripts=[script],
                    requirement_configuration=RequirementConfiguration(),
                    target_configuration=target_configuration,
                )
            except Unsatisfiable as e:
                return Error(str(e))
            if script_metadata_application.target_does_not_apply(target):
                targets = Targets.from_target(self._resolve_target(target_configuration, script))
            if script_metadata_application.requirement_configuration.requirements:
                requirements.update(
                    script_metadata_application.requirement_configuration.requirements
                )

        if not requirements:
            return ToolResolve(script=script)

        if pylock:
            resolved = lock_resolver.resolve_from_pylock(
                targets=targets,
                pylock=pylock,
                resolver=resolver,
                requirements=requirements,
                indexes=pip_configuration.repos_configuration.indexes,
                find_links=pip_configuration.repos_configuration.find_links,
                resolver_version=pip_configuration.resolver_version,
                network_configuration=pip_configuration.network_configuration,
                password_entries=pip_configuration.repos_configuration.password_entries,
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
                requirements=requirements,
                allow_prereleases=pip_configuration.allow_prereleases,
                transitive=pip_configuration.transitive,
                indexes=pip_configuration.repos_configuration.indexes,
                find_links=pip_configuration.repos_configuration.find_links,
                resolver_version=pip_configuration.resolver_version,
                network_configuration=pip_configuration.network_configuration,
                password_entries=pip_configuration.repos_configuration.password_entries,
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

        root_distributions = []  # type: List[Distribution]
        distributions = []  # type: List[Distribution]
        for resolved_dist in resolved.distributions:
            if resolved_dist.direct_requirements:
                root_distributions.append(resolved_dist.distribution)
            distributions.append(resolved_dist.distribution)
        production_assert(
            len(root_distributions) == 1,
            "Expected to resolve exactly one distribution for {requirement}, but found {count}.",
            requirement=run_config.requirement or run_config.entry_point,
            count=len(root_distributions),
        )

        return ToolResolve(
            run_distribution=root_distributions[0],
            distributions=tuple(distributions),
            script=script,
        )

    def _ensure_tool_venv(
        self,
        tool_venv_dir,  # type: str
        target_configuration,  # type: TargetConfiguration
        target,  # type: Target
        run_config,  # type: RunConfig
        repair=True,  # type: bool
    ):
        # type: (...) -> List[str]

        with atomic_directory(tool_venv_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                pylock = None  # type: Optional[Pylock]
                if run_config.locks and run_config.requirement:
                    package, maybe_lock = try_(
                        self._resolve_pylock(target, run_config.requirement, run_config.locks)
                    )
                    if not maybe_lock and run_config.locked_choice is LockedChoice.REQUIRE:
                        raise ResultError(
                            Error("A tool lock file was required but none was found.")
                        )
                    if maybe_lock:
                        pylock = try_(Pylock.parse(maybe_lock))
                        packages = list(pylock.packages)
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
                        local_project_requirement_mapping = {}
                        if isinstance(package.artifact, UnFingerprintedLocalProjectArtifact):
                            local_project_requirement_mapping[
                                package.artifact.directory
                            ] = package.as_requirement()

                        pylock = attr.evolve(
                            pylock,
                            packages=tuple(packages),
                            local_project_requirement_mapping=local_project_requirement_mapping,
                        )

                tool_resolve = try_(
                    self._resolve_tool(target_configuration, target, run_config, pylock=pylock)
                )
                with interpreter.path_mapping(atomic_dir.work_dir, tool_venv_dir):
                    venv = Virtualenv.create_atomic(
                        venv_dir=atomic_dir,
                        interpreter=PythonInterpreter.get(),
                    )
                    provenance = Provenance.create(
                        venv=venv, python=interpreter.adjust_to_final_path(venv.interpreter.binary)
                    )
                    installer.populate_venv_distributions(
                        venv=venv, distributions=tool_resolve.distributions, provenance=provenance
                    )

                if run_config.requirement_is_entry_point:
                    assert tool_resolve.run_distribution is not None
                    entry_point = EntryPoint(
                        type=EntryPointType.MODULE, value=tool_resolve.run_distribution.project_name
                    )
                else:
                    entry_point = self._calculate_entry_point(run_config, venv)
                    if entry_point.type is EntryPointType.SCRIPT:
                        production_assert(
                            tool_resolve.script is not None,
                            "Expected a script for {run_config}",
                            run_config=run_config,
                        )
                        dst = os.path.join(venv.venv_dir, entry_point.value)
                        # N.B.: MyPy does not see the production_assert above.
                        safe_copy(cast(str, tool_resolve.script), dst)
                entry_point.store(venv.venv_dir)

        venv = Virtualenv(tool_venv_dir)
        if not run_config.requirement_is_entry_point:
            entry_point = self._calculate_entry_point(run_config, venv)
            if entry_point.type is EntryPointType.SCRIPT and isinstance(
                run_config.entry_point, ArtifactURL
            ):
                dst = os.path.join(venv.venv_dir, entry_point.value)
                if not os.path.exists(dst):
                    pip_configuration = resolver_options.create_pip_configuration(self.options)
                    src = try_(self._resolve_script(run_config.entry_point, pip_configuration))
                    safe_copy(src, dst)
        else:
            ep = EntryPoint.load(tool_venv_dir)
            if isinstance(ep, Error):
                if repair:
                    # Old versions of `pex3 run` either did not record an DEFAULT-ENTRY-POINT file or
                    # else recorded a different schema; this serves to upgrade those venvs as needed.
                    safe_rmtree(tool_venv_dir)
                    return self._ensure_tool_venv(
                        tool_venv_dir, target_configuration, target, run_config, repair=False
                    )
                raise ResultError(error=ep)
            entry_point = ep
        return entry_point.command(venv, *run_config.args)

    @staticmethod
    def _calculate_entry_point(
        run_config,  # type: RunConfig
        venv,  # type: Virtualenv
    ):
        # type: (...) -> EntryPoint

        if isinstance(run_config.entry_point, ArtifactURL):
            name, ext = os.path.splitext(os.path.basename(run_config.entry_point.path))
            return EntryPoint(
                type=EntryPointType.SCRIPT,
                value="{name}.{hash}{ext}".format(
                    name=name,
                    hash=hashlib.sha1(
                        run_config.entry_point.normalized_url.encode("utf-8")
                    ).hexdigest(),
                    ext=ext,
                ),
            )

        console_script = venv.bin_path(run_config.entry_point)
        if os.path.isfile(console_script):
            script_relpath = os.path.relpath(console_script, venv.venv_dir)
            return EntryPoint(type=EntryPointType.CONSOLE_SCRIPT, value=script_relpath)

        return EntryPoint(type=EntryPointType.MODULE, value=run_config.entry_point)

    @staticmethod
    def _resolve_target(
        target_configuration,  # type: TargetConfiguration
        source,  # type: str
    ):
        # type: (...) -> Target
        return (
            try_(
                target_configuration.resolve_targets().require_at_most_one_target(
                    "resolving {source}".format(source=source)
                )
            )
            or LocalInterpreter.create()
        )

    def run(self):
        # type: () -> Result

        run_config = try_(self._parse_options())

        target_configuration = TargetConfiguration(
            interpreter_configuration=target_options.configure_interpreters(self.options)
        )
        if run_config.requirement:
            source = str(run_config.requirement)
        elif isinstance(run_config.entry_point, ArtifactURL):
            source = run_config.entry_point.normalized_url
        else:
            source = run_config.entry_point
        target = self._resolve_target(target_configuration, source=source)

        tool_venv_dir = venv_dir(
            pex_root=ENV.PEX_ROOT,
            pex_hash=run_config.fingerprint(target),
            has_interpreter_constraints=False,
        )
        if not os.path.exists(tool_venv_dir.path):
            cache_access.read_write()
        elif self.options.refresh:
            # TODO: XXX: Obtain cache write lock 1st.
            safe_rmtree(tool_venv_dir.path)
        command = self._ensure_tool_venv(
            tool_venv_dir.path, target_configuration, target, run_config
        )
        cache_access.record_access(tool_venv_dir)

        TRACER.log(
            "Running: {command}".format(command=" ".join(shlex_quote(arg) for arg in command))
        )
        safe_execv(command)
