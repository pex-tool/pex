# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
from abc import abstractmethod
from collections import OrderedDict, defaultdict

from pex import pex_warnings
from pex.common import pluralize
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Distribution, Requirement
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.pep_427 import InstallableType
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersionValue
from pex.resolve.lockfile.model import Lockfile
from pex.sorted_tuple import SortedTuple
from pex.targets import AbbreviatedPlatform, Target, Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, List, Optional, Tuple

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


def sorted_requirements(requirements):
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
        converter=sorted_requirements, factory=SortedTuple
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
        direct_requirements = sorted_requirements(direct_requirements)
        if direct_requirements == self.direct_requirements:
            return self
        return ResolvedDistribution(
            self.target,
            self.fingerprinted_distribution,
            direct_requirements=direct_requirements,
        )


def check_resolve(
    dependency_configuration,  # type: DependencyConfiguration
    resolved_distributions,  # type: Iterable[ResolvedDistribution]
):
    # type: (...) -> None

    resolved_distributions_by_project_name = (
        OrderedDict()
    )  # type: OrderedDict[ProjectName, List[ResolvedDistribution]]
    for resolved_distribution in resolved_distributions:
        resolved_distributions_by_project_name.setdefault(
            resolved_distribution.distribution.metadata.project_name, []
        ).append(resolved_distribution)

    maybe_unsatisfied = defaultdict(list)  # type: DefaultDict[Target, List[str]]
    unsatisfied = defaultdict(list)  # type: DefaultDict[Target, List[str]]

    def check(
        target,  # type: Target
        dist,  # type: Distribution
        requirement,  # type: Requirement
        root=False,  # type: bool
    ):
        # type: (...) -> None

        required_by = (
            "{requirement} was requested".format(requirement=requirement)
            if root
            else "{dist} requires {requirement}".format(dist=dist, requirement=requirement)
        )
        installed_requirement_dists = resolved_distributions_by_project_name.get(
            requirement.project_name
        )
        if not installed_requirement_dists:
            unsatisfied[target].append(
                "{required_by} but no version was resolved".format(required_by=required_by)
            )
        else:
            resolved_dists = [
                installed_requirement_dist.distribution
                for installed_requirement_dist in installed_requirement_dists
            ]
            version_matches = any(
                (
                    # We don't attempt a match against a legacy version in order to avoid false
                    # negatives.
                    resolved_dist.metadata.version.is_legacy
                    or requirement.specifier.contains(resolved_dist.version, prereleases=True)
                )
                for resolved_dist in resolved_dists
            )
            tags_match = any(
                target.wheel_applies(resolved_dist) for resolved_dist in resolved_dists
            )
            if not version_matches or not tags_match:
                message = (
                    "{required_by} but {count} incompatible {dists_were} resolved:\n"
                    "        {dists}".format(
                        required_by=required_by,
                        count=len(resolved_dists),
                        dists_were="dists were" if len(resolved_dists) > 1 else "dist was",
                        dists="\n        ".join(
                            os.path.basename(resolved_dist.location)
                            for resolved_dist in resolved_dists
                        ),
                    )
                )
                if version_matches and not tags_match and isinstance(target, AbbreviatedPlatform):
                    # We don't know for sure an abbreviated platform doesn't match a wheels tags
                    # until we are running on that platform; so just warn for these instead of
                    # hard erroring.
                    maybe_unsatisfied[target].append(message)
                else:
                    unsatisfied[target].append(message)

    for resolved_distribution in itertools.chain.from_iterable(
        resolved_distributions_by_project_name.values()
    ):
        target = resolved_distribution.target
        for root_req in resolved_distribution.direct_requirements:
            check(
                target=target,
                dist=resolved_distribution.distribution,
                requirement=root_req,
                root=True,
            )
        dist = resolved_distribution.distribution

        for requirement in dist.requires():
            if dependency_configuration.excluded_by(requirement):
                continue
            requirement = (
                dependency_configuration.overridden_by(requirement, target=target) or requirement
            )
            if not target.requirement_applies(requirement):
                continue
            check(target, dist, requirement)

    if unsatisfied:
        unsatisfieds = []
        for target, missing in unsatisfied.items():
            unsatisfieds.append(
                "{target} is not compatible with:\n    {missing}".format(
                    target=target.render_description(), missing="\n    ".join(missing)
                )
            )
        raise Unsatisfiable(
            "Failed to resolve compatible distributions for {count} {targets}:\n{failures}".format(
                count=len(unsatisfieds),
                targets=pluralize(unsatisfieds, "target"),
                failures="\n".join(
                    "{index}: {failure}".format(index=index, failure=failure)
                    for index, failure in enumerate(unsatisfieds, start=1)
                ),
            )
        )

    if maybe_unsatisfied:
        maybe_unsatisfieds = []
        for target, missing in maybe_unsatisfied.items():
            maybe_unsatisfieds.append(
                "{target} may not be compatible with:\n    {missing}".format(
                    target=target.render_description(), missing="\n    ".join(missing)
                )
            )
        pex_warnings.warn(
            "The resolved distributions for {count} {targets} may not be compatible:\n"
            "{failures}\n"
            "\n"
            "Its generally advisable to use `--complete-platform` instead of `--platform` to\n"
            "ensure resolved distributions will be compatible with the target platform at\n"
            "runtime. For instructions on how to generate a `--complete-platform` see:\n"
            "    https://docs.pex-tool.org/buildingpex.html#complete-platform ".format(
                count=len(maybe_unsatisfieds),
                targets=pluralize(maybe_unsatisfieds, "target"),
                failures="\n".join(
                    "{index}: {failure}".format(index=index, failure=failure)
                    for index, failure in enumerate(maybe_unsatisfieds, start=1)
                ),
            )
        )


@attr.s(frozen=True)
class ResolveResult(object):
    dependency_configuration = attr.ib()  # type: DependencyConfiguration
    distributions = attr.ib()  # type: Tuple[ResolvedDistribution, ...]
    type = attr.ib()  # type: InstallableType.Value


class Resolver(object):
    @abstractmethod
    def is_default_repos(self):
        # type: () -> bool
        raise NotImplementedError()

    def use_system_time(self):
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

    @abstractmethod
    def resolve_requirements(
        self,
        requirements,  # type: Iterable[str]
        targets=Targets(),  # type: Targets
        pip_version=None,  # type: Optional[PipVersionValue]
        transitive=None,  # type: Optional[bool]
        extra_resolver_requirements=None,  # type: Optional[Tuple[Requirement, ...]]
        result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    ):
        # type: (...) -> ResolveResult
        raise NotImplementedError()
