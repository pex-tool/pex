# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
import site
import sys
from collections import OrderedDict, defaultdict

from pex import dist_metadata, pex_warnings
from pex.common import pluralize
from pex.distribution_target import DistributionTarget
from pex.inherit_path import InheritPath
from pex.layout import maybe_install
from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName, distribution_satisfies_requirement
from pex.pex_info import PexInfo
from pex.third_party.packaging import specifiers, tags
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import DistributionHelper

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import (
        DefaultDict,
        FrozenSet,
        Iterable,
        Iterator,
        List,
        MutableMapping,
        Optional,
        Tuple,
        Union,
    )
else:
    from pex.third_party import attr


def _import_pkg_resources():
    try:
        import pkg_resources  # vendor:skip

        return pkg_resources, False
    except ImportError:
        from pex import third_party

        third_party.install(expose=["setuptools"])
        import pkg_resources  # vendor:skip

        return pkg_resources, True


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


@attr.s(frozen=True)
class _RankedDistribution(object):
    # N.B.: A distribution implements rich comparison with the leading component being the
    # `parsed_version`; as such, a _RankedDistribution sorts as a whole 1st by `rank` (which is a
    # rank of the distribution's tags specificity for the target interpreter), then by version and
    # finally by redundant components of distribution metadata we never get to since they are
    # encoded in the tag specificity rank value.

    @classmethod
    def maximum(cls, fingerprinted_distribution):
        # type: (FingerprintedDistribution) -> _RankedDistribution
        return cls(rank=sys.maxsize, fingerprinted_distribution=fingerprinted_distribution)

    rank = attr.ib()  # type: int
    fingerprinted_distribution = attr.ib()  # type: FingerprintedDistribution

    @property
    def distribution(self):
        # type: () -> Distribution
        return self.fingerprinted_distribution.distribution

    @property
    def fingerprint(self):
        # type: () -> str
        return self.fingerprinted_distribution.fingerprint

    def satisfies(self, requirement):
        # type: (Requirement) -> bool
        return distribution_satisfies_requirement(self.distribution, requirement)


@attr.s(frozen=True)
class _UnrankedDistribution(object):
    fingerprinted_distribution = attr.ib()  # type: FingerprintedDistribution

    @property
    def dist(self):
        # type: () -> Distribution
        return self.fingerprinted_distribution.distribution

    def render_message(self, target):
        # type: (DistributionTarget) -> str
        return "The distribution {dist} cannot be used by {target}.".format(
            dist=self.dist, target=target
        )


@attr.s(frozen=True)
class _InvalidWheelName(_UnrankedDistribution):
    filename = attr.ib()  # type: str

    def render_message(self, _target):
        # type: (DistributionTarget) -> str
        return (
            "The filename of {dist} is not a valid wheel file name that can be parsed for "
            "tags.".format(dist=self.dist)
        )


@attr.s(frozen=True)
class _TagMismatch(_UnrankedDistribution):
    wheel_tags = attr.ib()  # type: FrozenSet[tags.Tag]

    def render_message(self, target):
        # type: (DistributionTarget) -> str
        return (
            "The wheel tags for {dist} are {wheel_tags} which do not match the supported tags of "
            "{target}:\n{supported_tags}".format(
                dist=self.dist,
                wheel_tags=", ".join(map(str, self.wheel_tags)),
                target=target,
                supported_tags="\n".join(map(str, target.get_supported_tags())),
            )
        )


@attr.s(frozen=True)
class _PythonRequiresMismatch(_UnrankedDistribution):
    python_requires = attr.ib()  # type: specifiers.SpecifierSet

    def render_message(self, target):
        # type: (DistributionTarget) -> str
        return (
            "The distribution has a python requirement of {python_requires} which does not match "
            "the python version of {python_version} for {target}.".format(
                python_requires=self.python_requires,
                python_version=target.get_python_version_str(),
                target=target,
            )
        )


@attr.s(frozen=True)
class _QualifiedRequirement(object):
    requirement = attr.ib()  # type: Requirement
    required = attr.ib(default=True)  # type: Optional[bool]


@attr.s(frozen=True)
class _DistributionNotFound(object):
    requirement = attr.ib()  # type: Requirement
    required_by = attr.ib(default=None)  # type: Optional[Distribution]


if TYPE_CHECKING:
    QualifiedRequirementOrNotFound = Union[_QualifiedRequirement, _DistributionNotFound]


class ResolveError(Exception):
    """Indicates an error resolving requirements from within a PEX."""


@attr.s(frozen=True)
class _RequirementKey(ProjectName):
    @classmethod
    def create(cls, requirement):
        # type: (Requirement) -> _RequirementKey
        return cls(requirement, frozenset(requirement.extras))

    extras = attr.ib()  # type: FrozenSet[str]

    def satisfied_keys(self):
        # type: () -> Iterator[_RequirementKey]

        # If we resolve a requirement with extras then we've satisfied resolves for the powerset of
        # the extras.
        # For example, if we resolve `cake[birthday,wedding]` then we satisfy resolves for:
        # `cake[]`
        # `cake[birthday]`
        # `cake[wedding]`
        # `cake[birthday,wedding]`
        items = list(self.extras)
        for size in range(len(items) + 1):
            for combination_of_size in itertools.combinations(items, size):
                yield _RequirementKey(self.project_name, frozenset(combination_of_size))


class PEXEnvironment(object):
    @classmethod
    def mount(
        cls,
        pex,  # type: str
        pex_info=None,  # type: Optional[PexInfo]
        target=None,  # type: Optional[DistributionTarget]
    ):
        # type: (...) -> PEXEnvironment
        pi = pex_info or PexInfo.from_pex(pex)
        pex_hash = pi.pex_hash
        if pex_hash is None:
            raise AssertionError(
                "There was no pex_hash stored in {} for {}.".format(PexInfo.PATH, pex)
            )
        pex_root = pi.pex_root
        pex = maybe_install(pex=pex, pex_root=pex_root, pex_hash=pex_hash) or pex
        target = target or DistributionTarget.current()
        return cls(pex=pex, pex_info=pi, target=target)

    def __init__(
        self,
        pex,  # type: str
        pex_info=None,  # type: Optional[PexInfo]
        target=None,  # type: Optional[DistributionTarget]
    ):
        # type: (...) -> None
        self._pex_info = pex_info or PexInfo.from_pex(pex)
        self._pex = os.path.realpath(pex)

        self._available_ranked_dists_by_project_name = defaultdict(
            list
        )  # type: DefaultDict[ProjectName, List[_RankedDistribution]]
        self._unavailable_dists_by_project_name = defaultdict(
            list
        )  # type: DefaultDict[ProjectName, List[_UnrankedDistribution]]
        self._resolved_dists = None  # type: Optional[Iterable[Distribution]]
        self._activated_dists = None  # type: Optional[Iterable[Distribution]]

        self._target = target or DistributionTarget.current()
        self._interpreter_version = self._target.get_python_version_str()

        # The supported_tags come ordered most specific (platform specific) to least specific
        # (universal). We want to rank most specific highest; so we need to reverse iteration order
        # here.
        self._supported_tags_to_rank = {
            tag: rank for rank, tag in enumerate(reversed(self._target.get_supported_tags()))
        }
        self._platform, _ = self._target.get_platform()

    @property
    def path(self):
        # type: () -> str
        return self._pex

    def _load_internal_cache(self):
        # type: () -> Iterator[FingerprintedDistribution]
        internal_cache = os.path.join(self._pex, self._pex_info.internal_cache)
        with TRACER.timed("Searching dependency cache: %s" % internal_cache, V=2):
            for distribution_name, fingerprint in self._pex_info.distributions.items():
                dist_path = os.path.join(internal_cache, distribution_name)
                yield FingerprintedDistribution(
                    distribution=DistributionHelper.distribution_from_path(dist_path),
                    fingerprint=fingerprint,
                )

    def _update_candidate_distributions(self, distribution_iter):
        # type: (Iterable[FingerprintedDistribution]) -> None
        for fingerprinted_dist in distribution_iter:
            ranked_dist = self._can_add(fingerprinted_dist)
            project_name = fingerprinted_dist.project_name
            if isinstance(ranked_dist, _RankedDistribution):
                with TRACER.timed("Adding %s" % fingerprinted_dist.distribution, V=2):
                    self._available_ranked_dists_by_project_name[project_name].append(ranked_dist)
            else:
                self._unavailable_dists_by_project_name[project_name].append(ranked_dist)

    def _can_add(self, fingerprinted_dist):
        # type: (FingerprintedDistribution) -> Union[_RankedDistribution, _UnrankedDistribution]
        filename, ext = os.path.splitext(os.path.basename(fingerprinted_dist.location))
        if ext.lower() != ".whl":
            # This supports resolving pex's own vendored distributions which are vendored in directory
            # directory with the project name (`pip/` for pip) and not the corresponding wheel name
            # (`pip-19.3.1-py2.py3-none-any.whl/` for pip). Pex only vendors universal wheels for all
            # platforms it supports at buildtime and runtime so this is always safe.
            return _RankedDistribution.maximum(fingerprinted_dist)

        # Wheel filename format: https://www.python.org/dev/peps/pep-0427/#file-name-convention
        # `{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl`
        wheel_components = filename.split("-")
        if len(wheel_components) < 3:
            return _InvalidWheelName(fingerprinted_dist, filename)

        # `{python tag}-{abi tag}-{platform tag}`
        wheel_tags = tags.parse_tag("-".join(wheel_components[-3:]))
        # There will be multiple parsed tags for compressed tag sets. Ensure we grab the parsed tag
        # with highest rank from that expanded set.
        rank = max(self._supported_tags_to_rank.get(tag, -1) for tag in wheel_tags)
        if rank == -1:
            return _TagMismatch(fingerprinted_dist, wheel_tags)

        if self._interpreter_version:
            python_requires = dist_metadata.requires_python(fingerprinted_dist.distribution)
            if python_requires and self._interpreter_version not in python_requires:
                return _PythonRequiresMismatch(fingerprinted_dist, python_requires)

        return _RankedDistribution(rank, fingerprinted_dist)

    def activate(self):
        # type: () -> Iterable[Distribution]
        if self._activated_dists is None:
            with TRACER.timed("Activating PEX virtual environment from %s" % self._pex):
                self._activated_dists = self._activate()
        return self._activated_dists

    def _evaluate_marker(
        self,
        requirement,  # type: Requirement
        extras=None,  # type: Optional[Tuple[str, ...]]
    ):
        # type: (...) -> Optional[bool]
        applies = self._target.requirement_applies(requirement, extras=extras)
        if applies is False:
            TRACER.log(
                "Skipping activation of `{}` due to environment marker de-selection".format(
                    requirement
                ),
                V=3,
            )
        return applies

    def _resolve_requirement(
        self,
        requirement,  # type: Requirement
        resolved_dists_by_key,  # type: MutableMapping[_RequirementKey, FingerprintedDistribution]
        required,  # type: Optional[bool]
        required_by=None,  # type: Optional[Distribution]
    ):
        # type: (...) -> Iterator[_DistributionNotFound]
        requirement_key = _RequirementKey.create(requirement)
        if requirement_key in resolved_dists_by_key:
            return

        available_distributions = [
            ranked_dist
            for ranked_dist in self._available_ranked_dists_by_project_name[
                ProjectName(requirement)
            ]
            if ranked_dist.satisfies(requirement)
        ]
        if not available_distributions:
            if required is True:
                yield _DistributionNotFound(requirement, required_by=required_by)
            return

        resolved_distribution = sorted(available_distributions, reverse=True)[
            0
        ].fingerprinted_distribution
        if len(available_distributions) > 1:
            TRACER.log(
                "Resolved {req} to {dist} and discarded {discarded}.".format(
                    req=requirement,
                    dist=resolved_distribution.distribution,
                    discarded=", ".join(
                        str(ranked_dist.distribution) for ranked_dist in available_distributions[1:]
                    ),
                ),
                V=9,
            )

        resolved_dists_by_key.update(
            (key, resolved_distribution) for key in requirement_key.satisfied_keys()
        )

        for dep_requirement in dist_metadata.requires_dists(resolved_distribution.distribution):
            # A note regarding extras and why they're passed down one level (we don't pass / use
            # dep_requirement.extras for example):
            #
            # Say we're resolving the `requirement` 'requests[security]==2.25.1'. That means
            # `resolved_distribution` is the requests distribution. It will have metadata that
            # looks like so:
            #
            # $ grep Requires-Dist requests-2.25.1.dist-info/METADATA | grep security -C1
            # Requires-Dist: certifi (>=2017.4.17)
            # Requires-Dist: pyOpenSSL (>=0.14) ; extra == 'security'
            # Requires-Dist: cryptography (>=1.3.4) ; extra == 'security'
            # Requires-Dist: PySocks (!=1.5.7,>=1.5.6) ; extra == 'socks'
            #
            # We want to recurse and resolve all standard requests requirements but also those that
            # are part of the 'security' extra. In order to resolve the latter we need to include
            # the 'security' extra environment marker.
            required = self._evaluate_marker(dep_requirement, extras=requirement.extras)
            if required is False:
                continue

            for not_found in self._resolve_requirement(
                dep_requirement,
                resolved_dists_by_key,
                required,
                required_by=resolved_distribution,
            ):
                yield not_found

    def _root_requirements_iter(self, reqs):
        # type: (Iterable[Requirement]) -> Iterator[QualifiedRequirementOrNotFound]

        # We want to pick one requirement for each key (required project) to then resolve
        # recursively.

        # First, the selected requirement clearly needs to be applicable (its environment markers
        # must apply to our interpreter). For example, for a Python 3.6 interpreter this would
        # select just "isort==5.6.4; python_version>='3.6'" from the input set:
        # {
        #   "isort==4.3.21; python_version<'3.6'",
        #   "setuptools==44.1.1; python_version<'3.6'",
        #   "isort==5.6.4; python_version>='3.6'",
        # }
        qualified_reqs_by_project_name = (
            OrderedDict()
        )  # type: OrderedDict[ProjectName, List[_QualifiedRequirement]]
        for req in reqs:
            required = self._evaluate_marker(req)
            if required is False:
                continue
            project_name = ProjectName(req)
            requirements = qualified_reqs_by_project_name.get(project_name)
            if requirements is None:
                qualified_reqs_by_project_name[project_name] = requirements = []
            requirements.append(_QualifiedRequirement(req, required=required))

        # Next, from among the remaining applicable requirements for a given project, we want to
        # select the most tailored (highest ranked) available distribution. That distribution's
        # transitive requirements will later fill in the full resolve.
        for project_name, qualified_requirements in qualified_reqs_by_project_name.items():
            ranked_dists = self._available_ranked_dists_by_project_name.get(project_name)
            if ranked_dists is None:
                # We've winnowed down reqs_by_key to just those requirements whose environment
                # markers apply; so, we should always have an available distribution.
                message = (
                    "A distribution for {project_name} could not be resolved in this "
                    "environment.".format(project_name=project_name)
                )
                unavailable_dists = self._unavailable_dists_by_project_name.get(project_name)
                if unavailable_dists:
                    message += (
                        "Found {count} {distributions} for {project_name} that do not apply:\n"
                        "{unavailable_dists}".format(
                            count=len(unavailable_dists),
                            distributions=pluralize(unavailable_dists, "distribution"),
                            project_name=project_name,
                            unavailable_dists="\n".join(
                                "{index}.) {message}".format(
                                    index=index,
                                    message=unavailable_dist.render_message(self._target),
                                )
                                for index, unavailable_dist in enumerate(unavailable_dists, start=1)
                            ),
                        )
                    )
                raise ResolveError(message)
            candidates = [
                (ranked_dist, qualified_requirement)
                for qualified_requirement in qualified_requirements
                for ranked_dist in ranked_dists
                if ranked_dist.satisfies(qualified_requirement.requirement)
            ]
            if not candidates:
                for qualified_requirement in qualified_requirements:
                    yield _DistributionNotFound(qualified_requirement.requirement)
                continue

            ranked_dist, qualified_requirement = sorted(
                candidates, key=lambda tup: tup[0], reverse=True
            )[0]
            if len(candidates) > 1:
                TRACER.log(
                    "Selected {dist} via {req} and discarded {discarded}.".format(
                        req=qualified_requirement.requirement,
                        dist=ranked_dist.distribution,
                        discarded=", ".join(
                            "{dist} via {req}".format(
                                req=qualified_req.requirement, dist=ranked_dist.distribution
                            )
                            for ranked_dist, qualified_req in candidates[1:]
                        ),
                    ),
                    V=9,
                )
            yield qualified_requirement

    def resolve(self):
        # type: () -> Iterable[Distribution]
        if self._resolved_dists is None:
            all_reqs = [Requirement.parse(req) for req in self._pex_info.requirements]
            self._resolved_dists = tuple(
                fingerprinted_distribution.distribution
                for fingerprinted_distribution in self.resolve_dists(all_reqs)
            )
        return self._resolved_dists

    def resolve_dists(self, reqs):
        # type: (Iterable[Requirement]) -> Iterable[FingerprintedDistribution]

        self._update_candidate_distributions(self._load_internal_cache())

        unresolved_reqs = OrderedDict()  # type: OrderedDict[Requirement, OrderedSet]

        def record_unresolved(dist_not_found):
            # type: (_DistributionNotFound) -> None
            TRACER.log("Failed to resolve a requirement: {}".format(dist_not_found.requirement))
            requirers = unresolved_reqs.get(dist_not_found.requirement)
            if requirers is None:
                requirers = OrderedSet()
                unresolved_reqs[dist_not_found.requirement] = requirers
            if dist_not_found.required_by:
                requirers.add(dist_not_found.required_by)

        resolved_dists_by_key = (
            OrderedDict()
        )  # type: OrderedDict[_RequirementKey, FingerprintedDistribution]
        for qualified_req_or_not_found in self._root_requirements_iter(reqs):
            if isinstance(qualified_req_or_not_found, _DistributionNotFound):
                record_unresolved(qualified_req_or_not_found)
                continue

            with TRACER.timed("Resolving {}".format(qualified_req_or_not_found.requirement), V=2):
                for not_found in self._resolve_requirement(
                    requirement=qualified_req_or_not_found.requirement,
                    required=qualified_req_or_not_found.required,
                    resolved_dists_by_key=resolved_dists_by_key,
                ):
                    record_unresolved(not_found)

        if unresolved_reqs:
            TRACER.log("Unresolved requirements:")
            for req in unresolved_reqs:
                TRACER.log("  - {}".format(req))

            TRACER.log("Distributions contained within this pex:")
            if not self._pex_info.distributions:
                TRACER.log("  None")
            else:
                for dist_name in self._pex_info.distributions:
                    TRACER.log("  - {}".format(dist_name))

            if not self._pex_info.ignore_errors:
                items = []
                for index, (requirement, requirers) in enumerate(unresolved_reqs.items()):
                    rendered_requirers = ""
                    if requirers:
                        rendered_requirers = "\n    Required by:" "\n      {requirers}".format(
                            requirers="\n      ".join(map(str, requirers))
                        )
                    contains = self._available_ranked_dists_by_project_name[
                        ProjectName(requirement)
                    ]
                    if contains:
                        rendered_contains = (
                            "\n    But this pex only contains:"
                            "\n      {distributions}".format(
                                distributions="\n      ".join(
                                    os.path.basename(ranked_dist.distribution.location)
                                    for ranked_dist in contains
                                ),
                            )
                        )
                    else:
                        rendered_contains = (
                            "\n    But this pex had no {project_name!r} distributions.".format(
                                project_name=requirement.project_name
                            )
                        )
                    items.append(
                        "{index: 2d}: {requirement}"
                        "{rendered_requirers}"
                        "{rendered_contains}".format(
                            index=index + 1,
                            requirement=requirement,
                            rendered_requirers=rendered_requirers,
                            rendered_contains=rendered_contains,
                        )
                    )

                raise ResolveError(
                    "Failed to resolve requirements from PEX environment @ {pex}.\n"
                    "Needed {platform} compatible dependencies for:\n"
                    "{items}".format(pex=self._pex, platform=self._platform, items="\n".join(items))
                )

        return OrderedSet(resolved_dists_by_key.values())

    _NAMESPACE_PACKAGE_METADATA_RESOURCE = "namespace_packages.txt"

    @classmethod
    def _get_namespace_packages(cls, dist):
        if dist.has_metadata(cls._NAMESPACE_PACKAGE_METADATA_RESOURCE):
            return list(dist.get_metadata_lines(cls._NAMESPACE_PACKAGE_METADATA_RESOURCE))
        else:
            return []

    @classmethod
    def _declare_namespace_packages(cls, resolved_dists):
        # type: (Iterable[Distribution]) -> None
        namespace_packages_by_dist = OrderedDict()
        for dist in resolved_dists:
            namespace_packages = cls._get_namespace_packages(dist)
            # NB: Dists can explicitly declare empty namespace packages lists to indicate they have none.
            # We only care about dists with one or more namespace packages though; thus, the guard.
            if namespace_packages:
                namespace_packages_by_dist[dist] = namespace_packages

        if not namespace_packages_by_dist:
            return  # Nothing to do here.

        # When declaring namespace packages, we need to do so with the `setuptools` distribution that
        # will be active in the pex environment at runtime and, as such, care must be taken.
        #
        # Properly behaved distributions will declare a dependency on `setuptools`, in which case we
        # use that (non-vendored) distribution. A side-effect of importing `pkg_resources` from that
        # distribution is that a global `pkg_resources.working_set` will be populated. For various
        # `pkg_resources` distribution discovery functions to work, that global
        # `pkg_resources.working_set` must be built with the `sys.path` fully settled. Since all dists
        # in the dependency set (`resolved_dists`) have already been resolved and added to the
        # `sys.path` we're safe to proceed here.
        #
        # Other distributions (notably `twitter.common.*`) in the wild declare `setuptools`-specific
        # `namespace_packages` but do not properly declare a dependency on `setuptools` which they must
        # use to:
        # 1. Declare `namespace_packages` metadata which we just verified they have with the check
        #    above.
        # 2. Declare namespace packages at runtime via the canonical:
        #    `__import__('pkg_resources').declare_namespace(__name__)`
        #
        # For such distributions we fall back to our vendored version of `setuptools`. This is safe,
        # since we'll only introduce our shaded version when no other standard version is present and
        # even then tear it all down when we hand off from the bootstrap to user code.
        pkg_resources, vendored = _import_pkg_resources()
        if vendored:
            dists = "\n".join(
                "\n{index}. {dist} namespace packages:\n  {ns_packages}".format(
                    index=index + 1,
                    dist=dist.as_requirement(),
                    ns_packages="\n  ".join(ns_packages),
                )
                for index, (dist, ns_packages) in enumerate(namespace_packages_by_dist.items())
            )
            pex_warnings.warn(
                "The `pkg_resources` package was loaded from a pex vendored version when "
                "declaring namespace packages defined by:\n{dists}\n\nThese distributions "
                "should fix their `install_requires` to include `setuptools`".format(dists=dists)
            )

        for pkg in itertools.chain(*namespace_packages_by_dist.values()):
            if pkg in sys.modules:
                pkg_resources.declare_namespace(pkg)

    def _activate(self):
        # type: () -> Iterable[Distribution]

        if not any(self._pex == os.path.realpath(path) for path in sys.path):
            TRACER.log("Adding pex environment to the head of sys.path: {}".format(self._pex))
            sys.path.insert(0, self._pex)

        resolved = self.resolve()
        for dist in resolved:
            with TRACER.timed("Activating %s" % dist, V=2):
                if self._pex_info.inherit_path == InheritPath.FALLBACK:
                    # Prepend location to sys.path.
                    #
                    # This ensures that bundled versions of libraries will be used before system-installed
                    # versions, in case something is installed in both, helping to favor hermeticity in
                    # the case of non-hermetic PEX files (i.e. those with inherit_path=True).
                    #
                    # If the path is not already in sys.path, site.addsitedir will append (not prepend)
                    # the path to sys.path. But if the path is already in sys.path, site.addsitedir will
                    # leave sys.path unmodified, but will do everything else it would do. This is not part
                    # of its advertised contract (which is very vague), but has been verified to be the
                    # case by inspecting its source for both cpython 2.7 and cpython 3.7.
                    sys.path.insert(0, dist.location)
                else:
                    sys.path.append(dist.location)

                with TRACER.timed("Adding sitedir", V=2):
                    site.addsitedir(dist.location)
        return resolved
