# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Optional, Iterable
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class RequirementConfiguration(object):
    requirements = attr.ib(default=None)  # type: Optional[Iterable[str]]
    requirement_files = attr.ib(default=None)  # type: Optional[Iterable[str]]
    constraint_files = attr.ib(default=None)  # type: Optional[Iterable[str]]
