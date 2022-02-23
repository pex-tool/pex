# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.resolve.locked_resolve import LockedResolve
from pex.sorted_tuple import SortedTuple
from pex.targets import Target
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class ResolveError(Exception):
    """Indicates an error resolving requirements for a PEX."""


class Untranslatable(ResolveError):
    pass


class Unsatisfiable(ResolveError):
    pass


def _sorted_requirements(requirements):
    # type: (Optional[Iterable[Requirement]]) -> SortedTuple[Requirement]
    return SortedTuple(requirements, key=lambda req: str(req)) if requirements else SortedTuple()


@attr.s(frozen=True)
class InstalledDistribution(object):
    """A distribution target, and the installed distribution that satisfies it.

    If installed distribution directly satisfies a user-specified requirement, that requirement is
    included.
    """

    target = attr.ib()  # type: Target
    fingerprinted_distribution = attr.ib()  # type: FingerprintedDistribution
    direct_requirements = attr.ib(
        converter=_sorted_requirements, factory=SortedTuple
    )  # type: SortedTuple[Requirement]

    @property
    def distribution(self):
        # type: () -> Distribution
        return self.fingerprinted_distribution.distribution

    @property
    def fingerprint(self):
        # type: () -> str
        return self.fingerprinted_distribution.fingerprint

    def with_direct_requirements(self, direct_requirements=None):
        # type: (Optional[Iterable[Requirement]]) -> InstalledDistribution
        direct_requirements = _sorted_requirements(direct_requirements)
        if direct_requirements == self.direct_requirements:
            return self
        return InstalledDistribution(
            self.target,
            self.fingerprinted_distribution,
            direct_requirements=direct_requirements,
        )


@attr.s(frozen=True)
class Installed(object):
    installed_distributions = attr.ib()  # type: Tuple[InstalledDistribution, ...]
    locks = attr.ib(default=())  # type: Tuple[LockedResolve, ...]
