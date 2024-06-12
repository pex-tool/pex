# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.dist_metadata import Distribution, Requirement
from pex.pep_503 import ProjectName
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Mapping, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class DependencyConfiguration(object):
    @classmethod
    def create(
        cls,
        excluded=(),  # type: Iterable[str]
        overridden=(),  # type: Iterable[str]
    ):
        # type: (...) -> DependencyConfiguration
        return cls(
            excluded=tuple(Requirement.parse(req) for req in excluded),
            overridden={
                override.project_name: override for override in map(Requirement.parse, overridden)
            },
        )

    excluded = attr.ib(default=())  # type: Tuple[Requirement, ...]
    overridden = attr.ib(factory=dict)  # type: Mapping[ProjectName, Requirement]

    def configure(self, pex_info):
        # type: (PexInfo) -> None
        for excluded in self.excluded:
            pex_info.add_exclude(excluded)
        for override in self.overridden.values():
            pex_info.add_override(override)

    def excluded_by(self, item):
        # type: (Union[Distribution, Requirement]) -> Tuple[Requirement, ...]
        return tuple(req for req in self.excluded if item in req)

    def overridden_by(self, requirement):
        # type: (Requirement) -> Optional[Requirement]
        return self.overridden.get(requirement.project_name)
