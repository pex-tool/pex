# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
from collections import OrderedDict, defaultdict

from pex import environment
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Requirement
from pex.environment import PEXEnvironment
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_427 import InstallableType
from pex.pep_503 import ProjectName
from pex.pex_info import PexInfo
from pex.requirements import Constraint, LocalProjectRequirement, parse_requirement_strings
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolvers import ResolvedDistribution, ResolveResult, Unsatisfiable, Untranslatable
from pex.targets import Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, List, Optional


def resolve_from_pex(
    targets,  # type: Targets
    pex,  # type: str
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    transitive=True,  # type: bool
    ignore_errors=False,  # type: bool
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> ResolveResult

    pex_info = PexInfo.from_pex(pex)
    requirement_configuration = RequirementConfiguration(
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
    )
    root_reqs = requirement_configuration.parse_requirements(
        network_configuration=network_configuration
    ) or parse_requirement_strings(pex_info.requirements)

    direct_requirements_by_project_name = (
        OrderedDict()
    )  # type: OrderedDict[ProjectName, List[Requirement]]
    for direct_requirement in root_reqs:
        if isinstance(direct_requirement, LocalProjectRequirement):
            raise Untranslatable(
                "Cannot resolve local projects from PEX repositories. Asked to resolve {path} "
                "from {pex}.".format(path=direct_requirement.path, pex=pex)
            )
        direct_requirements_by_project_name.setdefault(
            direct_requirement.requirement.project_name, []
        ).append(direct_requirement.requirement)

    constraints_by_project_name = defaultdict(
        list
    )  # type: DefaultDict[ProjectName, List[Constraint]]
    if not ignore_errors:
        for constraint in requirement_configuration.parse_constraints(
            network_configuration=network_configuration
        ):
            constraints_by_project_name[constraint.requirement.project_name].append(constraint)

    dependency_configuration = DependencyConfiguration.from_pex_info(pex_info).merge(
        dependency_configuration
    )
    all_reqs = OrderedSet(
        itertools.chain.from_iterable(direct_requirements_by_project_name.values())
    )
    distributions = OrderedSet()  # type: OrderedSet[ResolvedDistribution]
    for target in targets.unique_targets():
        pex_env = PEXEnvironment.mount(pex, target=target)
        try:
            fingerprinted_distributions = pex_env.resolve_dists(
                all_reqs, result_type=result_type, dependency_configuration=dependency_configuration
            )
        except environment.ResolveError as e:
            raise Unsatisfiable(str(e))

        for fingerprinted_distribution in fingerprinted_distributions:
            project_name = fingerprinted_distribution.project_name
            direct_requirements = direct_requirements_by_project_name.get(project_name, [])
            if not transitive and not direct_requirements:
                continue

            unmet_constraints = [
                constraint
                for constraint in constraints_by_project_name.get(project_name, ())
                if fingerprinted_distribution.distribution not in constraint.requirement
            ]
            if unmet_constraints:
                raise Unsatisfiable(
                    "The following constraints were not satisfied by {dist} resolved from "
                    "{pex}:\n{constraints}".format(
                        dist=fingerprinted_distribution.location,
                        pex=pex,
                        constraints="\n".join(map(str, unmet_constraints)),
                    )
                )

            distributions.add(
                ResolvedDistribution(
                    target=target,
                    fingerprinted_distribution=fingerprinted_distribution,
                    direct_requirements=direct_requirements,
                )
            )
    return ResolveResult(
        dependency_configuration=dependency_configuration,
        distributions=tuple(distributions),
        type=result_type,
    )
