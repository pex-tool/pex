# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.third_party.packaging import utils as packaging_utils
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _canonicalize_version(version):
    # type: (str) -> str
    return cast(str, packaging_utils.canonicalize_version(version))


@attr.s(frozen=True)
class Version(object):
    """A PEP-440 normalized version: https://www.python.org/dev/peps/pep-0440/#normalization"""

    version = attr.ib(converter=_canonicalize_version)  # type: str

    def __str__(self):
        # type: () -> str
        return self.version
