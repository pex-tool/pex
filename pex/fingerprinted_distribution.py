# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.pep_503 import ProjectName
from pex.third_party.pkg_resources import Distribution
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class FingerprintedDistribution(object):
    distribution = attr.ib()  # type: Distribution
    fingerprint = attr.ib()  # type: str

    @property
    def location(self):
        # type: () -> str
        return cast(str, self.distribution.location)

    @property
    def project_name(self):
        # type: () -> ProjectName
        return ProjectName(self.distribution)
