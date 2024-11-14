# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import defaultdict

from pex import pex_warnings
from pex.common import pluralize
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Requirement
from pex.environment import PEXEnvironment
from pex.exceptions import production_assert
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.resolve.resolvers import ResolveResult
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s
class DependencyManager(object):
    _requirements = attr.ib(factory=OrderedSet)  # type: OrderedSet[Requirement]
    _distributions = attr.ib(factory=OrderedSet)  # type: OrderedSet[FingerprintedDistribution]

    def add_requirement(self, requirement):
        # type: (Requirement) -> None
        self._requirements.add(requirement)

    def add_distribution(self, fingerprinted_distribution):
        # type: (FingerprintedDistribution) -> None
        self._distributions.add(fingerprinted_distribution)

    def add_from_pex(
        self,
        pex,  # type: str
        result_type_wheel_file=False,  # type: bool
    ):
        # type: (...) -> PexInfo

        pex_info = PexInfo.from_pex(pex)
        for req in pex_info.requirements:
            self.add_requirement(Requirement.parse(req))

        pex_environment = PEXEnvironment.mount(pex, pex_info=pex_info)
        for dist in pex_environment.iter_distributions(
            result_type_wheel_file=result_type_wheel_file
        ):
            self.add_distribution(dist)

        return pex_info

    def add_from_resolved(self, resolved):
        # type: (ResolveResult) -> None

        for resolved_dist in resolved.distributions:
            for req in resolved_dist.direct_requirements:
                self.add_requirement(req)
            self.add_distribution(resolved_dist.fingerprinted_distribution)

    def configure(
        self,
        pex_builder,  # type: PEXBuilder
        dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> None

        dependency_configuration.configure(pex_builder.info)

        root_requirements_by_project_name = defaultdict(
            OrderedSet
        )  # type: DefaultDict[ProjectName, OrderedSet[Requirement]]
        for root_req in self._requirements:
            root_requirements_by_project_name[root_req.project_name].add(root_req)

        for fingerprinted_dist in self._distributions:
            excluded_by = dependency_configuration.excluded_by(fingerprinted_dist.distribution)
            if excluded_by:
                excludes = " and ".join(map(str, excluded_by))
                root_reqs = root_requirements_by_project_name[fingerprinted_dist.project_name]
                production_assert(
                    len(root_reqs) > 0,
                    "The deep --exclude mechanism failed to exclude {dist} from transitive "
                    "requirements. It should have been excluded by configured excludes: "
                    "{excludes} but was not.",
                    dist=fingerprinted_dist.distribution,
                    excludes=excludes,
                )
                pex_warnings.warn(
                    "The distribution {dist} was required by the input {requirements} "
                    "{root_reqs} but ultimately excluded by configured excludes: "
                    "{excludes}".format(
                        dist=fingerprinted_dist.distribution,
                        requirements=pluralize(root_reqs, "requirement"),
                        root_reqs=" and ".join(map(str, root_reqs)),
                        excludes=excludes,
                    )
                )
                continue
            pex_builder.add_distribution(
                dist=fingerprinted_dist.distribution, fingerprint=fingerprinted_dist.fingerprint
            )

        for requirement in self._requirements:
            pex_builder.add_requirement(requirement)
