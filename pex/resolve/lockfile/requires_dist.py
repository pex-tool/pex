# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import defaultdict, deque

from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Requirement
from pex.orderedset import OrderedSet
from pex.resolve.locked_resolve import LockedRequirement, LockedResolve
from pex.resolve.target_system import MarkerEnv, UniversalTarget
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, Iterator, Optional

    import attr  # vendor:skip

else:
    from pex.third_party import attr


def filter_dependencies(
    requirement,  # type: Requirement
    locked_requirement,  # type: LockedRequirement
    universal_target=None,  # type: Optional[UniversalTarget]
):
    # type: (...) -> Iterator[Requirement]

    marker_env = MarkerEnv.create(extras=requirement.extras, universal_target=universal_target)
    for dep in locked_requirement.requires_dists:
        if not dep.marker or marker_env.evaluate(dep.marker):
            yield dep


def remove_unused_requires_dist(
    resolve_requirements,  # type: Iterable[Requirement]
    locked_resolve,  # type: LockedResolve
    universal_target=None,  # type: Optional[UniversalTarget]
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> LockedResolve

    locked_req_by_project_name = {
        locked_req.pin.project_name: locked_req for locked_req in locked_resolve.locked_requirements
    }
    requires_dist_by_locked_req = defaultdict(
        OrderedSet
    )  # type: DefaultDict[LockedRequirement, OrderedSet[Requirement]]
    seen = set()
    requirements = deque(resolve_requirements)
    while requirements:
        requirement = requirements.popleft()
        if requirement in seen:
            continue

        seen.add(requirement)
        locked_req = locked_req_by_project_name.get(requirement.project_name)
        if not locked_req:
            continue

        for dep in filter_dependencies(requirement, locked_req, universal_target=universal_target):
            if dependency_configuration.excluded_by(dep):
                continue
            if any(
                d.project_name in locked_req_by_project_name
                for d in dependency_configuration.overrides_for(dep) or [dep]
            ):
                requires_dist_by_locked_req[locked_req].add(dep)
                requirements.append(dep)

    return attr.evolve(
        locked_resolve,
        locked_requirements=SortedTuple(
            attr.evolve(
                locked_requirement,
                requires_dists=SortedTuple(
                    requires_dist_by_locked_req[locked_requirement], key=str
                ),
            )
            for locked_requirement in locked_resolve.locked_requirements
        ),
    )
