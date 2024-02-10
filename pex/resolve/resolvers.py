# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from abc import abstractmethod

from pex.dist_metadata import Distribution, Requirement
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.pep_427 import InstallableType
from pex.pip.version import PipVersionValue
from pex.resolve.lockfile.model import Lockfile
from pex.sorted_tuple import SortedTuple
from pex.targets import Target, Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


# Derived from notes in the bandersnatch PyPI mirroring tool:
# https://github.com/pypa/bandersnatch/blob/1485712d6aa77fba54bbf5a2df0d7314124ad097/src/bandersnatch/default.conf#L30-L35
MAX_PARALLEL_DOWNLOADS = 10


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
class ResolvedDistribution(object):
    """A distribution target, and the resolved distribution that satisfies it.

    If the resolved distribution directly satisfies a user-specified requirement, that requirement
    is included.
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
        # type: (Optional[Iterable[Requirement]]) -> ResolvedDistribution
        direct_requirements = _sorted_requirements(direct_requirements)
        if direct_requirements == self.direct_requirements:
            return self
        return ResolvedDistribution(
            self.target,
            self.fingerprinted_distribution,
            direct_requirements=direct_requirements,
        )


@attr.s(frozen=True)
class ResolveResult(object):
    distributions = attr.ib()  # type: Tuple[ResolvedDistribution, ...]
    type = attr.ib()  # type: InstallableType.Value


class Resolver(object):
    @abstractmethod
    def is_default_repos(self):
        # type: () -> bool
        raise NotImplementedError()

    @abstractmethod
    def resolve_lock(
        self,
        lock,  # type: Lockfile
        targets=Targets(),  # type: Targets
        pip_version=None,  # type: Optional[PipVersionValue]
        result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    ):
        # type: (...) -> ResolveResult
        raise NotImplementedError()

    def resolve_requirements(
        self,
        requirements,  # type: Iterable[str]
        targets=Targets(),  # type: Targets
        pip_version=None,  # type: Optional[PipVersionValue]
        result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    ):
        # type: (...) -> ResolveResult
        raise NotImplementedError()
