# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
from argparse import Namespace, _ActionsContainer

from pex.build_system import pep_517
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import DistMetadata, Requirement
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.interpreter import PythonInterpreter
from pex.jobs import Raise, SpawnedJob, execute_parallel
from pex.pep_427 import InstallableType
from pex.pip.version import PipVersionValue
from pex.resolve.configured_resolve import resolve
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import Resolver, Untranslatable
from pex.targets import LocalInterpreter, Target, Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, List, Optional, Set, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class BuiltProject(object):
    target = attr.ib()  # type: Target
    fingerprinted_distribution = attr.ib()  # type: FingerprintedDistribution

    def as_requirement(self):
        # type: () -> Requirement
        return self.fingerprinted_distribution.distribution.as_requirement()

    @property
    def requires_dists(self):
        # type: () -> Tuple[Requirement, ...]
        return self.fingerprinted_distribution.distribution.metadata.requires_dists


@attr.s(frozen=True)
class Projects(object):
    paths = attr.ib(default=())  # type: Tuple[str, ...]

    @paths.validator
    def _is_project_dir(
        self,
        attribute,  # type: attr.Attribute
        value,  # type: Tuple[str, ...]
    ):
        # type: (...) -> None
        invalid_paths = []  # type: List[str]
        for path in value:
            if os.path.isfile(os.path.join(path, "pyproject.toml")):
                continue
            if os.path.isfile(os.path.join(path, "setup.py")):
                continue
            invalid_paths.append(path)

        if invalid_paths:
            raise ValueError(
                "The following --project paths do not appear to point to directories containing "
                "Python projects:\n"
                "{invalid_paths}".format(
                    invalid_paths="\n".join(
                        "{index}. {path}".format(index=index, path=path)
                        for index, path in enumerate(invalid_paths, start=1)
                    )
                )
            )

    def build(
        self,
        targets,  # type: Targets
        pip_configuration,  # type: PipConfiguration
        compile_pyc=False,  # type: bool
        ignore_errors=False,  # type: bool
        result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
        dependency_config=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> Iterator[BuiltProject]

        resolve_result = resolve(
            targets=targets,
            requirement_configuration=RequirementConfiguration(requirements=self.paths),
            resolver_configuration=attr.evolve(pip_configuration, transitive=False),
            compile_pyc=compile_pyc,
            ignore_errors=ignore_errors,
            result_type=result_type,
            dependency_configuration=dependency_config,
        )
        for resolved_distribution in resolve_result.distributions:
            yield BuiltProject(
                target=resolved_distribution.target,
                fingerprinted_distribution=resolved_distribution.fingerprinted_distribution,
            )

    def collect_requirements(
        self,
        resolver,  # type: Resolver
        interpreter=None,  # type: Optional[PythonInterpreter]
        pip_version=None,  # type: Optional[PipVersionValue]
        max_jobs=None,  # type: Optional[int]
    ):
        # type: (...) -> Iterator[Requirement]

        target = LocalInterpreter.create(interpreter)

        def spawn_func(project_directory):
            # type: (str) -> SpawnedJob[DistMetadata]
            return pep_517.spawn_prepare_metadata(
                project_directory, target, resolver, pip_version=pip_version
            )

        seen = set()  # type: Set[Requirement]
        for dist_metadata in execute_parallel(
            self.paths,
            spawn_func=spawn_func,
            error_handler=Raise[str, DistMetadata](Untranslatable),
            max_jobs=max_jobs,
        ):
            for req in dist_metadata.requires_dists:
                if req not in seen:
                    seen.add(req)
                    yield req

    def __len__(self):
        # type: () -> int
        return len(self.paths)


def register_options(
    parser,  # type: _ActionsContainer
    help,  # type: str
):
    # type: (...) -> None

    parser.add_argument(
        "--project",
        dest="projects",
        metavar="DIR",
        default=[],
        type=str,
        action="append",
        help=help,
    )


def get_projects(options):
    # type: (Namespace) -> Projects
    return Projects(paths=tuple(options.projects))
