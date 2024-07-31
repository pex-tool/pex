# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools

from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Optional, Text, Union

    import attr  # vendor:skip
    from packaging import utils as packaging_utils  # vendor:skip
    from packaging import version as packaging_version  # vendor:skip
    from packaging.version import InvalidVersion  # vendor:skip

    ParsedVersion = Union[packaging_version.LegacyVersion, packaging_version.Version]
else:
    from pex.third_party import attr
    from pex.third_party.packaging import utils as packaging_utils
    from pex.third_party.packaging import version as packaging_version
    from pex.third_party.packaging.version import InvalidVersion


def _ensure_ascii_str(text):
    # type: (Text) -> str

    # Version numbers must be composed of ASCII as spelled out here:
    #  https://peps.python.org/pep-0440/#summary-of-changes-to-pep-440
    return str(text)


@functools.total_ordering
@attr.s(frozen=True, order=False)
class Version(object):
    """A PEP-440 normalized version: https://www.python.org/dev/peps/pep-0440/#normalization"""

    raw = attr.ib(eq=False, converter=_ensure_ascii_str)  # type: str
    normalized = attr.ib(init=False)  # type: str
    _parsed_version = attr.ib(
        default=None, init=False, eq=False, repr=False
    )  # type: Optional[ParsedVersion]

    def __attrs_post_init__(self):
        # type: () -> None

        # Although https://www.python.org/dev/peps/pep-0440 which does not allow a `-` in modern
        # versions, it also stipulates that all versions (legacy) must be handled. It turns out
        # wheel normalizes `-` to `_` and Pip has had to deal with this:
        #   https://github.com/pypa/pip/issues/1150
        #
        # We deal with this similarly.
        object.__setattr__(
            self,
            "normalized",
            cast(str, packaging_utils.canonicalize_version(self.raw)).replace("-", "_"),
        )

    @property
    def parsed_version(self):
        # type: () -> ParsedVersion
        if self._parsed_version is not None:
            return self._parsed_version

        parsed_version = packaging_version.parse(self.raw)
        object.__setattr__(self, "_parsed_version", parsed_version)
        return parsed_version

    def __lt__(self, other):
        # type: (Any) -> bool
        if not isinstance(other, Version):
            return NotImplemented
        return self.parsed_version < other.parsed_version

    def __ge__(self, other):
        # type: (Any) -> bool
        if not isinstance(other, Version):
            return NotImplemented
        return self.parsed_version >= other.parsed_version

    @property
    def is_legacy(self):
        # type: () -> bool
        try:
            return self.parsed_version is None
        except InvalidVersion:
            return True

    def __str__(self):
        # type: () -> str
        return self.normalized
