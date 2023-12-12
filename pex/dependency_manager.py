# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import defaultdict

from pex import pex_warnings
from pex.dist_metadata import Requirement
from pex.environment import PEXEnvironment
from pex.exclude_configuration import ExcludeConfiguration
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.resolve.resolvers import ResolveResult
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Iterator

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s
class DependencyManager(object):
    _requirements = attr.ib(factory=OrderedSet)  # type: OrderedSet[Requirement]
    _distributions = attr.ib(factory=OrderedSet)  # type: OrderedSet[FingerprintedDistribution]

    def add_from_pex(self, pex):
        # type: (str) -> PexInfo

        pex_info = PexInfo.from_pex(pex)
        self._requirements.update(Requirement.parse(req) for req in pex_info.requirements)

        pex_environment = PEXEnvironment.mount(pex, pex_info=pex_info)
        self._distributions.update(pex_environment.iter_distributions())

        return pex_info

    def add_from_resolved(self, resolved):
        # type: (ResolveResult) -> None

        for resolved_dist in resolved.distributions:
            self._requirements.update(resolved_dist.direct_requirements)
            self._distributions.add(resolved_dist.fingerprinted_distribution)

    def configure(
        self,
        pex_builder,  # type: PEXBuilder
        excluded=(),  # type: Iterable[str]
    ):
        # type: (...) -> None

        exclude_configuration = ExcludeConfiguration.create(excluded)
        exclude_configuration.configure(pex_builder.info)

        dists_by_project_name = defaultdict(
            OrderedSet
        )  # type: DefaultDict[ProjectName, OrderedSet[FingerprintedDistribution]]
        for dist in self._distributions:
            dists_by_project_name[dist.distribution.metadata.project_name].add(dist)

        root_requirements_by_project_name = defaultdict(
            OrderedSet
        )  # type: DefaultDict[ProjectName, OrderedSet[Requirement]]
        for root_req in self._requirements:
            root_requirements_by_project_name[root_req.project_name].add(root_req)

        def iter_non_excluded_distributions(requirements):
            # type: (Iterable[Requirement]) -> Iterator[FingerprintedDistribution]
            for req in requirements:
                candidate_dists = dists_by_project_name[req.project_name]
                for candidate_dist in tuple(candidate_dists):
                    if candidate_dist.distribution not in req:
                        continue
                    candidate_dists.discard(candidate_dist)

                    excluded_by = exclude_configuration.excluded_by(candidate_dist.distribution)
                    if excluded_by:
                        excludes = " and ".join(map(str, excluded_by))
                        TRACER.log(
                            "Skipping adding {candidate}: excluded by {excludes}".format(
                                candidate=candidate_dist.distribution, excludes=excludes
                            )
                        )
                        for root_req in root_requirements_by_project_name[
                            candidate_dist.distribution.metadata.project_name
                        ]:
                            if candidate_dist.distribution in root_req:
                                pex_warnings.warn(
                                    "The distribution {dist} was required by the input requirement "
                                    "{root_req} but excluded by configured excludes: "
                                    "{excludes}".format(
                                        dist=candidate_dist.distribution,
                                        root_req=root_req,
                                        excludes=excludes,
                                    )
                                )
                        continue

                    yield candidate_dist
                    for dep in iter_non_excluded_distributions(
                        candidate_dist.distribution.requires()
                    ):
                        yield dep

        for fingerprinted_dist in iter_non_excluded_distributions(self._requirements):
            pex_builder.add_distribution(
                dist=fingerprinted_dist.distribution, fingerprint=fingerprinted_dist.fingerprint
            )

        for requirement in self._requirements:
            pex_builder.add_requirement(requirement)
