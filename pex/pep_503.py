# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re

from pex.third_party.packaging.utils import canonicalize_name
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Text

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _ensure_ascii_str(text):
    # type: (Text) -> str

    # Although not crisply defined, all PEPs lead to PEP-508 which restricts project names to
    # ASCII: https://peps.python.org/pep-0508/#names
    return str(text)


@attr.s(frozen=True)
class ProjectName(object):
    """Encodes a canonicalized project name as per PEP-503.

    See: https://www.python.org/dev/peps/pep-0503/#normalized-names
    """

    class InvalidError(ValueError):
        """Indicates an invalid project name as per https://peps.python.org/pep-0508/#names."""

    # See: https://peps.python.org/pep-0508/#names
    _VALID_RE = re.compile(r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", re.IGNORECASE)

    raw = attr.ib(eq=False, converter=_ensure_ascii_str)  # type: str
    validated = attr.ib(eq=False, default=False)  # type: bool
    normalized = attr.ib(init=False)  # type: str

    def __attrs_post_init__(self):
        if self.validated and not self._VALID_RE.match(self.raw):
            raise self.InvalidError(
                "The given project name {value!r} is not a valid. It must conform to the regex "
                "{pattern!r} as specified in https://peps.python.org/pep-0508/#names".format(
                    value=self.raw, pattern=self._VALID_RE.pattern
                )
            )
        object.__setattr__(self, "normalized", canonicalize_name(self.raw))

    def __str__(self):
        # type: () -> str
        return self.normalized
