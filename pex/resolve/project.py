# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
from argparse import Namespace, _ActionsContainer

from pex import requirements, toml
from pex.build_system import pep_517
from pex.common import pluralize
from pex.compatibility import string
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import DistMetadata, Requirement, RequirementParseError
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.interpreter import PythonInterpreter
from pex.jobs import Raise, SpawnedJob, execute_parallel
from pex.orderedset import OrderedSet
from pex.pep_427 import InstallableType
from pex.pep_503 import ProjectName
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
    from typing import Any, Iterable, Iterator, List, Mapping, Optional, Set, Tuple, Union

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


@attr.s(frozen=True)
class GroupName(ProjectName):
    # N.B.: A dependency group name follows the same rules, including canonicalization, as project
    # names.
    pass


@attr.s(frozen=True)
class DependencyGroup(object):
    @classmethod
    def parse(cls, spec):
        # type: (str) -> DependencyGroup

        group, sep, project_dir = spec.partition("@")
        abs_project_dir = os.path.realpath(project_dir)
        if not os.path.isdir(abs_project_dir):
            raise ValueError(
                "The project directory specified by '{spec}' is not a directory".format(spec=spec)
            )

        pyproject_toml = os.path.join(abs_project_dir, "pyproject.toml")
        if not os.path.isfile(pyproject_toml):
            raise ValueError(
                "The project directory specified by '{spec}' does not contain a pyproject.toml "
                "file".format(spec=spec)
            )

        group_name = GroupName(group)
        try:
            dependency_groups = {
                GroupName(name): group
                for name, group in toml.load(pyproject_toml)["dependency-groups"].items()
            }  # type: Mapping[GroupName, Any]
        except (IOError, OSError, KeyError, ValueError, AttributeError) as e:
            raise ValueError(
                "Failed to read `[dependency-groups]` metadata from {pyproject_toml} when parsing "
                "dependency group spec '{spec}': {err}".format(
                    pyproject_toml=pyproject_toml, spec=spec, err=e
                )
            )
        if group_name not in dependency_groups:
            raise KeyError(
                "The dependency group '{group}' specified by '{spec}' does not exist in "
                "{pyproject_toml}".format(group=group, spec=spec, pyproject_toml=pyproject_toml)
            )

        return cls(project_dir=abs_project_dir, name=group_name, groups=dependency_groups)

    project_dir = attr.ib()  # type: str
    name = attr.ib()  # type: GroupName
    _groups = attr.ib()  # type: Mapping[GroupName, Any]

    def _parse_group_items(
        self,
        group,  # type: GroupName
        required_by=None,  # type: Optional[GroupName]
    ):
        # type: (...) -> Iterator[Union[GroupName, Requirement]]

        members = self._groups.get(group)
        if not members:
            if not required_by:
                raise KeyError(
                    "The dependency group '{group}' does not exist in the project at "
                    "{project_dir}.".format(group=group, project_dir=self.project_dir)
                )
            else:
                raise KeyError(
                    "The dependency group '{group}' required by dependency group '{required_by}' "
                    "does not exist in the project at {project_dir}.".format(
                        group=group, required_by=required_by, project_dir=self.project_dir
                    )
                )

        if not isinstance(members, list):
            raise ValueError(
                "Invalid dependency group '{group}' in the project at {project_dir}.\n"
                "The value must be a list containing dependency specifiers or dependency group "
                "includes.\n"
                "See https://peps.python.org/pep-0735/#specification for the specification "
                "of [dependency-groups] syntax."
            )

        for index, item in enumerate(members, start=1):
            if isinstance(item, string):
                try:
                    yield Requirement.parse(item)
                except RequirementParseError as e:
                    raise ValueError(
                        "Invalid [dependency-group] entry '{name}'.\n"
                        "Item {index}: '{req}', is an invalid dependency specifier: {err}".format(
                            name=group.raw, index=index, req=item, err=e
                        )
                    )
            elif isinstance(item, dict):
                try:
                    yield GroupName(item["include-group"])
                except KeyError:
                    raise ValueError(
                        "Invalid [dependency-group] entry '{name}'.\n"
                        "Item {index} is a non 'include-group' table and only dependency "
                        "specifiers and single entry 'include-group' tables are allowed in group "
                        "dependency lists.\n"
                        "See https://peps.python.org/pep-0735/#specification for the specification "
                        "of [dependency-groups] syntax.\n"
                        "Given: {item}".format(name=group.raw, index=index, item=item)
                    )
            else:
                raise ValueError(
                    "Invalid [dependency-group] entry '{name}'.\n"
                    "Item {index} is not a dependency specifier or a dependency group include.\n"
                    "See https://peps.python.org/pep-0735/#specification for the specification "
                    "of [dependency-groups] syntax.\n"
                    "Given: {item}".format(name=group.raw, index=index, item=item)
                )

    def iter_requirements(self):
        # type: () -> Iterator[Requirement]

        visited_groups = set()  # type: Set[GroupName]

        def iter_group(
            group,  # type: GroupName
            required_by=None,  # type: Optional[GroupName]
        ):
            # type: (...) -> Iterator[Requirement]
            if group not in visited_groups:
                visited_groups.add(group)
                for item in self._parse_group_items(group, required_by=required_by):
                    if isinstance(item, Requirement):
                        yield item
                    else:
                        for req in iter_group(item, required_by=group):
                            yield req

        return iter_group(self.name)


def register_options(
    parser,  # type: _ActionsContainer
    project_help,  # type: str
):
    # type: (...) -> None

    parser.add_argument(
        "--project",
        dest="projects",
        metavar="DIR",
        default=[],
        type=str,
        action="append",
        help=project_help,
    )

    parser.add_argument(
        "--group",
        "--dependency-group",
        dest="dependency_groups",
        metavar="GROUP[@DIR]",
        default=[],
        type=DependencyGroup.parse,
        action="append",
        help=(
            "Pull requirements from the specified PEP-735 dependency group. Dependency groups are "
            "specified by referencing the group name in a given project's pyproject.toml in the "
            "form `<group name>@<project directory>`; e.g.: `test@local/project/directory`. If "
            "either the `@<project directory>` suffix is not present or the suffix is just `@`, "
            "the current working directory is assumed to be the project directory to read the "
            "dependency group information from. Multiple dependency groups across any number of "
            "projects can be specified. Read more about dependency groups at "
            "https://peps.python.org/pep-0735/."
        ),
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


def get_group_requirements(options):
    # type: (Namespace) -> Iterable[Requirement]

    group_requirements = OrderedSet()  # type: OrderedSet[Requirement]
    for dependency_group in options.dependency_groups:
        for requirement in dependency_group.iter_requirements():
            group_requirements.add(requirement)
    return group_requirements
