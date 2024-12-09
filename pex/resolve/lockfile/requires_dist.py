# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.resolve.locked_resolve import LockedResolve
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
else:
    from pex.third_party import attr


def remove_unused_requires_dist(locked_resolve):
    # type: (LockedResolve) -> LockedResolve

    locked_projects = {
        locked_req.pin.project_name for locked_req in locked_resolve.locked_requirements
    }
    return attr.evolve(
        locked_resolve,
        locked_requirements=SortedTuple(
            attr.evolve(
                locked_requirement,
                requires_dists=SortedTuple(
                    (
                        requires_dist
                        for requires_dist in locked_requirement.requires_dists
                        # Otherwise, the requirement markers were never selected in the resolve
                        # process; so the requirement was not locked.
                        if requires_dist.project_name in locked_projects
                    ),
                    key=str,
                ),
            )
            for locked_requirement in locked_resolve.locked_requirements
        ),
    )
