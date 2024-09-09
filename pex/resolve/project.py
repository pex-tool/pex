# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Namespace, _ActionsContainer

from pex import requirements
from pex.build_system import pep_517
from pex.common import pluralize
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import DistMetadata, Requirement
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.interpreter import PythonInterpreter
from pex.jobs import Raise, SpawnedJob, execute_parallel
from pex.pep_427 import InstallableType
from pex.pip.version import PipVersionValue
from pex.requirements import LocalProjectRequirement, ParseError
from pex.resolve.configured_resolve import resolve
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolvers import Resolver, Untranslatable
from pex.sorted_tuple import SortedTuple
from pex.targets import LocalInterpreter, Target, Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator, List, Optional, Set, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _iter_requirements(
    target,  # type: Target
    dist_metadata,  # type: DistMetadata
    extras,  # type: Iterable[str]
):
    # type: (...) -> Iterator[Requirement]
    for req in dist_metadata.requires_dists:
        if not target.requirement_applies(requirement=req, extras=extras):
            continue
        yield attr.evolve(req, marker=None)


@attr.s(frozen=True)
class BuiltProject(object):
    target = attr.ib()  # type: Target
    fingerprinted_distribution = attr.ib()  # type: FingerprintedDistribution
    satisfied_direct_requirements = attr.ib()  # type: SortedTuple[Requirement]

    def iter_requirements(self):
        # type: () -> Iterator[Requirement]
        seen = set()  # type: Set[Requirement]
        for satisfied_direct_requirement in self.satisfied_direct_requirements:
            for req in _iter_requirements(
                target=self.target,
                dist_metadata=self.fingerprinted_distribution.distribution.metadata,
                extras=satisfied_direct_requirement.extras,
            ):
                if req not in seen:
                    seen.add(req)
                    yield req


@attr.s(frozen=True)
class Project(object):
    path = attr.ib()  # type: str
    requirement = attr.ib()  # type: LocalProjectRequirement

    @property
    def requirement_str(self):
        # type: () -> str
        # N.B.: Requirements are ASCII text. See: https://peps.python.org/pep-0508/#grammar
        return str(self.requirement.line.processed_text)


@attr.s(frozen=True)
class Projects(object):
    projects = attr.ib(default=())  # type: Tuple[Project, ...]

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
            requirement_configuration=RequirementConfiguration(
                requirements=[project.requirement_str for project in self.projects]
            ),
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
                satisfied_direct_requirements=resolved_distribution.direct_requirements,
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

        def spawn_func(project):
            # type: (Project) -> SpawnedJob[DistMetadata]
            return pep_517.spawn_prepare_metadata(
                project.path, target, resolver, pip_version=pip_version
            )

        seen = set()  # type: Set[Requirement]
        for local_project, dist_metadata in zip(
            self.projects,
            execute_parallel(
                self.projects,
                spawn_func=spawn_func,
                error_handler=Raise[Project, DistMetadata](Untranslatable),
                max_jobs=max_jobs,
            ),
        ):
            for req in _iter_requirements(
                target=target, dist_metadata=dist_metadata, extras=local_project.requirement.extras
            ):
                if req not in seen:
                    seen.add(req)
                    yield req

    def __len__(self):
        # type: () -> int
        return len(self.projects)


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

    projects = []  # type: List[Project]
    errors = []  # type: List[str]
    for project in options.projects:
        try:
            parsed = requirements.parse_requirement_string(project)
        except (ParseError, ValueError) as e:
            errors.append(
                "The --project {project} is not a valid local project requirement: {err}".format(
                    project=project, err=e
                )
            )
        else:
            if isinstance(parsed, LocalProjectRequirement):
                if parsed.marker:
                    errors.append(
                        "The --project {project} has a marker, which is not supported. "
                        "Remove marker: ;{marker}".format(project=project, marker=parsed.marker)
                    )
                else:
                    projects.append(Project(path=parsed.path, requirement=parsed))
            else:
                errors.append(
                    "The --project {project} does not appear to point to a directory containing a "
                    "Python project.".format(project=project)
                )

    if errors:
        raise ValueError(
            "Found {count} invalid --project {specifiers}:\n{errors}".format(
                count=len(errors),
                specifiers=pluralize(errors, "specifier"),
                errors="\n".join(
                    "{index}. {error}".format(index=index, error=error)
                    for index, error in enumerate(errors, start=1)
                ),
            )
        )

    return Projects(projects=tuple(projects))
