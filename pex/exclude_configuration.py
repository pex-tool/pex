# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.dist_metadata import Distribution, Requirement
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class ExcludeConfiguration(object):
    @classmethod
    def create(cls, excluded):
        # type: (Iterable[str]) -> ExcludeConfiguration
        return cls(excluded=tuple(Requirement.parse(req) for req in excluded))

    _excluded = attr.ib(factory=tuple)  # type: Tuple[Requirement, ...]

    def configure(self, pex_info):
        # type: (PexInfo) -> None
        for excluded in self._excluded:
            pex_info.add_excluded(excluded)

    def excluded_by(self, item):
        # type: (Union[Distribution, Requirement]) -> Iterable[Requirement]
        if isinstance(item, Distribution):
            return tuple(req for req in self._excluded if item in req)
        return tuple(req for req in self._excluded if item.project_name == req.project_name)
