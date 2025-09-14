from __future__ import absolute_import

import itertools
from collections import defaultdict

from pex.interpreter_constraints import iter_compatible_versions
from pex.interpreter_implementation import InterpreterImplementation
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.requirements import LocalProjectRequirement
from pex.resolve.package_repository import ReposConfiguration
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.target_system import MarkerEnv, TargetSystem, UniversalTarget, has_marker
from pex.targets import LocalInterpreter, Targets
from pex.third_party.packaging.markers import Marker
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, Dict, FrozenSet, Iterator, List, Mapping, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _calculate_split_markers(
    requirement_configuration,  # type: RequirementConfiguration
    network_configuration,  # type: NetworkConfiguration
    repos_configuration,  # type: ReposConfiguration
):
    # type: (...) -> Mapping[str, Marker]

    split_markers = {
        str(scope.marker): scope.marker
        for repo in itertools.chain(
            repos_configuration.index_repos, repos_configuration.find_links_repos
        )
        for scope in repo.scopes
        if scope.marker
    }

    projects_with_markers = defaultdict(dict)  # type: DefaultDict[ProjectName, Dict[str, Marker]]
    for requirement in requirement_configuration.parse_requirements(network_configuration):
        if not isinstance(requirement, LocalProjectRequirement) and requirement.marker:
            projects_with_markers[requirement.project_name][
                str(requirement.marker)
            ] = requirement.marker
    for constraint in requirement_configuration.parse_constraints(network_configuration):
        if constraint.marker:
            projects_with_markers[constraint.project_name][
                str(constraint.marker)
            ] = constraint.marker
    split_markers.update(
        (marker_str, marker)
        for markers in projects_with_markers.values()
        for marker_str, marker in markers.items()
        # N.B.: We only split the universal resolve for root requirements that have two or
        # more marker variants. If there is just one, that represents a conditional
        # dependency which can be included in a single resolve without splitting.
        if len(markers) > 1
    )

    return split_markers


def _iter_universal_targets(
    universal_target,  # type: UniversalTarget
    split_markers,  # type: Mapping[str, Marker]
):
    # type: (...) -> Iterator[UniversalTarget]

    target_systems = universal_target.systems or TargetSystem.values()

    interpreter_implementations = (
        (universal_target.implementation,)
        if universal_target.implementation
        else InterpreterImplementation.values()
    )

    requires_pythons = OrderedSet()  # type: OrderedSet[SpecifierSet]
    has_python_version = any(
        has_marker(marker, "python_version") for marker in split_markers.values()
    )
    has_python_full_version = any(
        has_marker(marker, "python_full_version") for marker in split_markers.values()
    )
    if has_python_full_version:
        requires_pythons.update(
            SpecifierSet(
                "=={major}.{minor}.{patch}".format(
                    major=version[0], minor=version[1], patch=version[2]
                )
            )
            for version in iter_compatible_versions(universal_target.requires_python)
        )
    elif has_python_version:
        requires_pythons.update(
            SpecifierSet("=={major}.{minor}.*".format(major=version[0], minor=version[1]))
            for version in OrderedSet(
                version[:2]
                for version in iter_compatible_versions(universal_target.requires_python)
            )
        )
    else:
        requires_pythons.update(universal_target.requires_python)
    if not requires_pythons:
        requires_pythons.add(SpecifierSet())

    systems_by_markers = defaultdict(
        list
    )  # type: DefaultDict[FrozenSet[str], List[Tuple[TargetSystem.Value, InterpreterImplementation.Value, SpecifierSet]]]
    for system in target_systems:
        for implementation in interpreter_implementations:
            for python_specifier in requires_pythons:
                marker_env = MarkerEnv.create(
                    extras=(),
                    universal_target=UniversalTarget(
                        implementation=implementation,
                        systems=(system,),
                        requires_python=(python_specifier,),
                    ),
                )
                system_repo_markers = frozenset(
                    marker_str
                    for marker_str, marker in split_markers.items()
                    if marker_env.evaluate(marker)
                )
                systems_by_markers[system_repo_markers].append(
                    (system, implementation, python_specifier)
                )

    for markers, value in systems_by_markers.items():
        systems = OrderedSet()  # type: OrderedSet[TargetSystem.Value]
        implementations = OrderedSet()  # type: OrderedSet[InterpreterImplementation.Value]
        requires_python = OrderedSet()  # type: OrderedSet[SpecifierSet]
        for system, implementation, python_specifier in value:
            systems.add(system)
            implementations.add(implementation)
            requires_python.add(python_specifier)
        impl = implementations.pop() if len(implementations) == 1 else None
        yield UniversalTarget(
            implementation=impl,
            systems=tuple(systems),
            requires_python=tuple(requires_python),
        )


@attr.s(frozen=True)
class LockTargets(object):
    @classmethod
    def calculate(
        cls,
        targets,  # type: Targets
        requirement_configuration,  # type: RequirementConfiguration
        network_configuration,  # type: NetworkConfiguration
        repos_configuration,  # type: ReposConfiguration
        universal_target=None,  # type: Optional[UniversalTarget]
    ):
        # type: (...) -> LockTargets

        if not universal_target:
            return cls(targets=targets)

        targets = Targets.from_target(LocalInterpreter.create(targets.interpreter))
        split_markers = _calculate_split_markers(
            requirement_configuration, network_configuration, repos_configuration
        )
        if not split_markers:
            return cls(targets=targets, universal_targets=(universal_target,))

        return cls(
            targets=targets,
            universal_targets=tuple(_iter_universal_targets(universal_target, split_markers)),
        )

    targets = attr.ib()  # type: Targets
    universal_targets = attr.ib(default=())  # type: Tuple[UniversalTarget, ...]
