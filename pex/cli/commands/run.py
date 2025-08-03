# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import hashlib
import json
import os.path
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
from pex.common import open_zip, safe_mkdtemp, safe_rmtree
from pex.compatibility import shlex_quote
from pex.dist_metadata import DistMetadata, is_sdist, is_tar_sdist, is_wheel
from pex.enum import Enum
from pex.exceptions import production_assert
from pex.interpreter import PythonInterpreter
from pex.os import safe_execv
from pex.requirements import LocalProjectRequirement, parse_requirement_string
from pex.resolve import lock_resolver, resolver_options, target_options
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.locked_resolve import FileArtifact, UnFingerprintedLocalProjectArtifact
from pex.resolve.lockfile.pep_751 import Dependency, Package, Pylock
from pex.resolve.resolvers import ResolveResult
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
    entry_point = attr.ib()  # type: str
    requirement = attr.ib()  # type: ParsedRequirement
    entry_point_is_requirement = attr.ib()  # type: bool
    args = attr.ib(default=())  # type: Tuple[str, ...]
    locks = attr.ib(default=())  # type: Tuple[str, ...]
    locked_choice = attr.ib(default=LockedChoice.AUTO)  # type: LockedChoice.Value

    def fingerprint(self, target):
        # type: (Target) -> str

        return hashlib.sha1(
            json.dumps(
                {
                    "requirement": (
                        str(self.requirement.path)
                        if isinstance(self.requirement, LocalProjectRequirement)
                        else str(self.requirement.requirement)
                    ),
                    "target": {
                        "markers": target.marker_environment.as_dict(),
                        "tag": str(target.platform.supported_tags[0]),
                    },
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()


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
        # type: () -> RunConfig

        entry_point = self.options.entry_point[0]

        locks = []  # type: List[str]
        if self.options.locked is not LockedChoice.IGNORE:
            locks.append("pylock.{entry_point}.toml".format(entry_point=entry_point))
            locks.append("pylock.toml")

        return RunConfig(
            entry_point=entry_point,
            requirement=parse_requirement_string(self.options.requirement or entry_point),
            entry_point_is_requirement=not self.options.requirement,
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
        # type: (...) -> Union[Optional[Tuple[Package, str]], Error]

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
        return None

    def _resolve_tool(
        self,
        target,  # type: Target
        requirement,  # type: ParsedRequirement
        pylock=None,  # type: Optional[Pylock]
    ):
        # type: (...) -> Union[ResolveResult, Error]

        pip_configuration = resolver_options.create_pip_configuration(self.options)
        resolver = ConfiguredResolver(pip_configuration=pip_configuration)
        targets = Targets.from_target(target)
        dep_config = dependency_configuration.configure(self.options)

        requirements = [str(requirement)]
        if pylock:
            return lock_resolver.resolve_from_pylock(
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
            return pip_resolver.resolve(
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

    def _ensure_tool_venv(
        self,
        tool_venv_dir,  # type: str
        target,  # type: Target
        run_config,  # type: RunConfig
        repair=True,  # type: bool
    ):
        # type: (...) -> List[str]

        with atomic_directory(tool_venv_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                pylock = None  # type: Optional[Pylock]
                if run_config.locks:
                    maybe_lock = try_(
                        self._resolve_pylock(target, run_config.requirement, run_config.locks)
                    )
                    if not maybe_lock and run_config.locked_choice is LockedChoice.REQUIRE:
                        raise ResultError(
                            Error("A tool lock file was required but none was found.")
                        )
                    if maybe_lock:
                        package, pylock_toml = maybe_lock
                        pylock = try_(Pylock.parse(pylock_toml))
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

                resolved = try_(self._resolve_tool(target, run_config.requirement, pylock=pylock))
                distributions = tuple(
                    resolved_distribution.distribution
                    for resolved_distribution in resolved.distributions
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
                        venv=venv, distributions=distributions, provenance=provenance
                    )

                if isinstance(run_config.requirement, LocalProjectRequirement):
                    with open(os.path.join(atomic_dir.work_dir, "DEFAULT-ENTRY-POINT"), "w") as fp:
                        fp.write(package.project_name.raw)

        if not run_config.entry_point_is_requirement:
            entry_point = run_config.entry_point
        elif isinstance(run_config.requirement, LocalProjectRequirement):
            entry_point_file = os.path.join(tool_venv_dir, "DEFAULT-ENTRY-POINT")
            if repair and not os.path.isfile(entry_point_file):
                # Old versions of `pex3 run` did not record an ENTRY-POINT file; this serves to
                # upgrade those venvs as needed.
                safe_rmtree(tool_venv_dir)
                return self._ensure_tool_venv(tool_venv_dir, target, run_config, repair=False)

            with open(entry_point_file) as fp:
                entry_point = fp.read()
        else:
            parsed_requirement = run_config.requirement
            packaging_requirement = parsed_requirement.requirement
            entry_point = packaging_requirement.project_name.raw

        venv = Virtualenv(tool_venv_dir)
        command = []  # type: List[str]

        script = venv.bin_path(entry_point)
        if os.path.isfile(script):
            command.append(script)
        else:
            command.extend((venv.interpreter.binary, "-m", entry_point))
        command.extend(run_config.args)
        return command

    def run(self):
        # type: () -> Result

        run_config = self._parse_options()

        target_configuration = TargetConfiguration(
            interpreter_configuration=target_options.configure_interpreters(self.options)
        )
        target = (
            try_(
                target_configuration.resolve_targets().require_at_most_one_target(
                    "resolving {requirement}".format(requirement=run_config.requirement)
                )
            )
            or LocalInterpreter.create()
        )

        tool_venv_dir = venv_dir(
            pex_root=ENV.PEX_ROOT,
            pex_hash=run_config.fingerprint(target),
            has_interpreter_constraints=False,
        )
        if not os.path.exists(tool_venv_dir.path):
            cache_access.read_write()
        elif self.options.refresh:
            safe_rmtree(tool_venv_dir.path)
        command = self._ensure_tool_venv(tool_venv_dir.path, target, run_config)
        cache_access.record_access(tool_venv_dir)

        TRACER.log(
            "Running: {command}".format(command=" ".join(shlex_quote(arg) for arg in command))
        )
        safe_execv(command)
