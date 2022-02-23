# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
from collections import OrderedDict, defaultdict

from pex import environment
from pex.environment import PEXEnvironment
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.requirements import Constraint, LocalProjectRequirement
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolvers import Installed, InstalledDistribution, Unsatisfiable, Untranslatable
from pex.targets import Targets
from pex.third_party.pkg_resources import Requirement
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
):
    # type: (...) -> Installed

    requirement_configuration = RequirementConfiguration(
        requirements=requirements,
        requirement_files=requirement_files,
        constraint_files=constraint_files,
    )
    direct_requirements_by_project_name = (
        OrderedDict()
    )  # type: OrderedDict[ProjectName, List[Requirement]]
    for direct_requirement in requirement_configuration.parse_requirements(
        network_configuration=network_configuration
    ):
        if isinstance(direct_requirement, LocalProjectRequirement):
            raise Untranslatable(
                "Cannot resolve local projects from PEX repositories. Asked to resolve {path} "
                "from {pex}.".format(path=direct_requirement.path, pex=pex)
            )
        direct_requirements_by_project_name.setdefault(
            ProjectName(direct_requirement.requirement), []
        ).append(direct_requirement.requirement)

    constraints_by_project_name = defaultdict(
        list
    )  # type: DefaultDict[ProjectName, List[Constraint]]
    if not ignore_errors:
        for contraint in requirement_configuration.parse_constraints(
            network_configuration=network_configuration
        ):
            constraints_by_project_name[ProjectName(contraint.requirement)].append(contraint)

    all_reqs = OrderedSet(
        itertools.chain.from_iterable(direct_requirements_by_project_name.values())
    )
    installed_distributions = OrderedSet()  # type: OrderedSet[InstalledDistribution]
    for target in targets.unique_targets():
        pex_env = PEXEnvironment.mount(pex, target=target)
        try:
            fingerprinted_distributions = pex_env.resolve_dists(all_reqs)
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

            installed_distributions.add(
                InstalledDistribution(
                    target=target,
                    fingerprinted_distribution=fingerprinted_distribution,
                    direct_requirements=direct_requirements,
                )
            )
    return Installed(installed_distributions=tuple(installed_distributions))
