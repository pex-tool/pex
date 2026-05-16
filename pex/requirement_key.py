# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.dist_metadata import Requirement
from pex.pep_503 import ProjectName
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import FrozenSet

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class RequirementKey(object):
    @classmethod
    def create(cls, requirement):
        # type: (Requirement) -> RequirementKey
        return cls(requirement.project_name, requirement.extras)

    project_name = attr.ib()  # type: ProjectName
    extras = attr.ib()  # type: FrozenSet[str]

    def satisfies(self, requested):
        # type: (RequirementKey) -> bool

        # A resolved requirement satisfies a requested requirement when the project names match
        # and the resolved extras are a superset of the requested extras.
        # For example, resolving `cake[birthday,wedding]` satisfies requests for:
        # `cake[]`
        # `cake[birthday]`
        # `cake[wedding]`
        # `cake[birthday,wedding]`
        return self.project_name == requested.project_name and requested.extras <= self.extras
