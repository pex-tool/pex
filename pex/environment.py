# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import importlib
import itertools
import os
import site
import sys
import zipfile
from collections import OrderedDict, defaultdict, namedtuple

from pex import dist_metadata, pex_builder, pex_warnings
from pex.bootstrap import Bootstrap
from pex.common import atomic_directory, open_zip
from pex.distribution_target import DistributionTarget
from pex.inherit_path import InheritPath
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.third_party.packaging import tags
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper, DistributionHelper

if TYPE_CHECKING:
    from typing import (
        Container,
        DefaultDict,
        Iterable,
        Iterator,
        List,
        MutableMapping,
        Optional,
        Tuple,
        Union,
    )


def _import_pkg_resources():
    try:
        import pkg_resources  # vendor:skip

        return pkg_resources, False
    except ImportError:
        from pex import third_party

        third_party.install(expose=["setuptools"])
        import pkg_resources  # vendor:skip

        return pkg_resources, True


class _RankedDistribution(namedtuple("_RankedDistribution", ["rank", "distribution"])):
    # N.B.: A distribution implements rich comparison with the leading component being the
    # `parsed_version`; as such, a _RankedDistribution sorts as a whole 1st by `rank` (which is a
    # rank of the distribution's tags specificity for the target interpreter), then by version and
    # finally by redundant components of distribution metadata we never get to since they are
    # encoded in the tag specificity rank value.

    @classmethod
    def maximum(cls, distribution=None):
        # type: (Optional[Distribution]) -> _RankedDistribution
        return cls(rank=sys.maxsize, distribution=distribution)

    @property
    def distribution(self):
        # type: () -> Distribution
        return cast(Distribution, super(_RankedDistribution, self).distribution)

    def satisfies(self, requirement):
        # type: (Requirement) -> bool
        return self.distribution in requirement


class _QualifiedRequirement(namedtuple("_QualifiedRequirement", ["requirement", "required"])):
    @classmethod
    def create(
        cls,
        requirement,  # type: Requirement
        required=True,  # type: Optional[bool]
    ):
        # type: (...) -> _QualifiedRequirement
        return cls(requirement=requirement, required=required)

    @property
    def requirement(self):
        # type: () -> Requirement
        return cast(Requirement, super(_QualifiedRequirement, self).requirement)

    @property
    def required(self):
        # type: () -> Optional[bool]
        return cast("Optional[bool]", super(_QualifiedRequirement, self).required)


if TYPE_CHECKING:
    QualifiedRequirementOrNotFound = Union[_QualifiedRequirement, _DistributionNotFound]


class _DistributionNotFound(namedtuple("_DistributionNotFound", ["requirement", "required_by"])):
    @classmethod
    def create(
        cls,
        requirement,  # type: Requirement
        required_by=None,  # type: Optional[Distribution]
    ):
        # type: (...) -> _DistributionNotFound
        return cls(requirement=requirement, required_by=required_by)


class ResolveError(Exception):
    """Indicates an error resolving requirements for a PEX."""


class _RequirementKey(namedtuple("_RequirementKey", ["key", "extras"])):
    @classmethod
    def create(cls, requirement):
        # type: (Requirement) -> _RequirementKey
        return cls(requirement.key, frozenset(requirement.extras))

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
                yield _RequirementKey(self.key, frozenset(combination_of_size))


class PEXEnvironment(object):
    class _CachingZipImporter(object):
        class _CachingLoader(object):
            def __init__(self, delegate):
                self._delegate = delegate

            def load_module(self, fullname):
                loaded = sys.modules.get(fullname)
                # Technically a PEP-302 loader should re-load the existing module object here - notably
                # re-exec'ing the code found in the zip against the existing module __dict__. We don't do
                # this since the zip is assumed immutable during our run and this is enough to work around
                # the issue.
                if not loaded:
                    loaded = self._delegate.load_module(fullname)
                    loaded.__loader__ = self
                return loaded

        _REGISTERED = False

        @classmethod
        def _ensure_namespace_handler_registered(cls):
            if not cls._REGISTERED:
                pkg_resources, _ = _import_pkg_resources()
                pkg_resources.register_namespace_handler(cls, pkg_resources.file_ns_handler)
                cls._REGISTERED = True

        def __init__(self, path):
            import zipimport

            self._delegate = zipimport.zipimporter(path)

        def find_module(self, fullname, path=None):
            loader = self._delegate.find_module(fullname, path)
            if loader is None:
                return None
            self._ensure_namespace_handler_registered()
            caching_loader = self._CachingLoader(loader)
            return caching_loader

    @classmethod
    def _install_pypy_zipimporter_workaround(cls, pex_file):
        # The pypy zipimporter implementation always freshly loads a module instead of re-importing
        # when the module already exists in sys.modules. This breaks the PEP-302 importer protocol and
        # violates pkg_resources assumptions based on that protocol in its handling of namespace
        # packages. See: https://bitbucket.org/pypy/pypy/issues/1686

        def pypy_zipimporter_workaround(path):
            import os

            if not path.startswith(pex_file) or "." in os.path.relpath(path, pex_file):
                # We only need to claim the pex zipfile root modules.
                #
                # The protocol is to raise if we don't want to hook the given path.
                # See: https://www.python.org/dev/peps/pep-0302/#specification-part-2-registering-hooks
                raise ImportError()

            return cls._CachingZipImporter(path)

        for path in list(sys.path_importer_cache):
            if path.startswith(pex_file):
                sys.path_importer_cache.pop(path)

        sys.path_hooks.insert(0, pypy_zipimporter_workaround)

    def explode_code(
        self,
        dest_dir,  # type: str
        exclude=(),  # type: Container[str]
    ):
        # type: (...) -> Iterable[Tuple[str, str]]
        with TRACER.timed("Unzipping {}".format(self._pex)):
            with open_zip(self._pex) as pex_zip:
                pex_files = (
                    name
                    for name in pex_zip.namelist()
                    if not name.startswith(pex_builder.BOOTSTRAP_DIR)
                    and not name.startswith(self._pex_info.internal_cache)
                    and name not in exclude
                )
                pex_zip.extractall(dest_dir, pex_files)
                return [
                    (
                        "{pex_file}:{zip_path}".format(pex_file=self._pex, zip_path=f),
                        os.path.join(dest_dir, f),
                    )
                    for f in pex_files
                ]

    def _force_local(self):
        if self._pex_info.code_hash is None:
            # Do not support force_local if code_hash is not set. (It should always be set.)
            return self._pex
        explode_dir = os.path.join(self._pex_info.zip_unsafe_cache, self._pex_info.code_hash)
        TRACER.log("PEX is not zip safe, exploding to %s" % explode_dir)
        with atomic_directory(explode_dir, exclusive=True) as explode_tmp:
            if explode_tmp:
                self.explode_code(explode_tmp)
        return explode_dir

    def _update_module_paths(self):
        bootstrap = Bootstrap.locate()

        # Un-import any modules already loaded from within the .pex file.
        to_reimport = []
        for name, module in reversed(sorted(sys.modules.items())):
            if bootstrap.imported_from_bootstrap(module):
                TRACER.log("Not re-importing module %s from bootstrap." % module, V=3)
                continue

            pkg_path = getattr(module, "__path__", None)
            if pkg_path and any(
                os.path.realpath(path_item).startswith(self._pex) for path_item in pkg_path
            ):
                sys.modules.pop(name)
                to_reimport.append((name, pkg_path, True))
            elif (
                name != "__main__"
            ):  # The __main__ module is special in python and is not re-importable.
                mod_file = getattr(module, "__file__", None)
                if mod_file and os.path.realpath(mod_file).startswith(self._pex):
                    sys.modules.pop(name)
                    to_reimport.append((name, mod_file, False))

        # And re-import them from the exploded pex.
        for name, existing_path, is_pkg in to_reimport:
            TRACER.log(
                "Re-importing %s %s loaded via %r from exploded pex."
                % ("package" if is_pkg else "module", name, existing_path)
            )
            reimported_module = importlib.import_module(name)
            if is_pkg:
                for path_item in existing_path:
                    # NB: It is not guaranteed that __path__ is a list, it may be a PEP-420 namespace package
                    # object which supports a limited mutation API; so we append each item individually.
                    reimported_module.__path__.append(path_item)

    def _write_zipped_internal_cache(self, zf):
        cached_distributions = []
        for distribution_name, dist_digest in self._pex_info.distributions.items():
            internal_dist_path = "/".join([self._pex_info.internal_cache, distribution_name])
            cached_location = os.path.join(
                self._pex_info.install_cache, dist_digest, distribution_name
            )
            dist = CacheHelper.cache_distribution(zf, internal_dist_path, cached_location)
            cached_distributions.append(dist)
        return cached_distributions

    def _load_internal_cache(self):
        """Possibly cache out the internal cache."""
        internal_cache = os.path.join(self._pex, self._pex_info.internal_cache)
        with TRACER.timed("Searching dependency cache: %s" % internal_cache, V=2):
            if len(self._pex_info.distributions) == 0:
                # We have no .deps to load.
                return

            if os.path.isdir(self._pex):
                for distribution_name in self._pex_info.distributions:
                    yield DistributionHelper.distribution_from_path(
                        os.path.join(internal_cache, distribution_name)
                    )
            else:
                with open_zip(self._pex) as zf:
                    for dist in self._write_zipped_internal_cache(zf):
                        yield dist

    def __init__(
        self,
        pex,  # type: str
        pex_info=None,  # type: Optional[PexInfo]
        target=None,  # type: Optional[DistributionTarget]
    ):
        # type: (...) -> None
        self._pex = os.path.realpath(pex)
        self._pex_info = pex_info or PexInfo.from_pex(pex)

        self._available_ranked_dists_by_key = defaultdict(
            list
        )  # type: DefaultDict[str, List[_RankedDistribution]]
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

        # For the bug this works around, see: https://bitbucket.org/pypy/pypy/issues/1686
        # NB: This must be installed early before the underlying pex is loaded in any way.
        if self._platform.impl == "pp" and zipfile.is_zipfile(self._pex):
            self._install_pypy_zipimporter_workaround(self._pex)

    def _update_candidate_distributions(self, distribution_iter):
        # type: (Iterable[Distribution]) -> None
        for dist in distribution_iter:
            ranked_dist = self._can_add(dist)
            if ranked_dist is not None:
                with TRACER.timed("Adding %s" % dist, V=2):
                    self._available_ranked_dists_by_key[dist.key].append(ranked_dist)

    def _can_add(self, dist):
        # type: (Distribution) -> Optional[_RankedDistribution]
        filename, ext = os.path.splitext(os.path.basename(dist.location))
        if ext.lower() != ".whl":
            # This supports resolving pex's own vendored distributions which are vendored in directory
            # directory with the project name (`pip/` for pip) and not the corresponding wheel name
            # (`pip-19.3.1-py2.py3-none-any.whl/` for pip). Pex only vendors universal wheels for all
            # platforms it supports at buildtime and runtime so this is always safe.
            return _RankedDistribution.maximum(dist)

        # Wheel filename format: https://www.python.org/dev/peps/pep-0427/#file-name-convention
        # `{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl`
        wheel_components = filename.split("-")
        if len(wheel_components) < 3:
            return None

        # `{python tag}-{abi tag}-{platform tag}`
        wheel_tags = tags.parse_tag("-".join(wheel_components[-3:]))
        # There will be multiple parsed tags for compressed tag sets. Ensure we grab the parsed tag
        # with highest rank from that expanded set.
        rank = max(self._supported_tags_to_rank.get(tag, -1) for tag in wheel_tags)
        if rank == -1:
            return None

        if self._interpreter_version:
            python_requires = dist_metadata.requires_python(dist)
            if python_requires and self._interpreter_version not in python_requires:
                return None

        return _RankedDistribution(rank, dist)

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
        resolved_dists_by_key,  # type: MutableMapping[Distribution, _RequirementKey]
        required,  # type: Optional[bool]
        required_by=None,  # type: Optional[Distribution]
    ):
        # type: (...) -> Iterator[_DistributionNotFound]
        requirement_key = _RequirementKey.create(requirement)
        if requirement_key in resolved_dists_by_key:
            return

        available_distributions = [
            ranked_dist
            for ranked_dist in self._available_ranked_dists_by_key.get(requirement.key, [])
            if ranked_dist.satisfies(requirement)
        ]
        if not available_distributions:
            if required is True:
                yield _DistributionNotFound.create(requirement, required_by=required_by)
            return

        resolved_distribution = sorted(available_distributions, reverse=True)[0].distribution
        if len(available_distributions) > 1:
            TRACER.log(
                "Resolved {req} to {dist} and discarded {discarded}.".format(
                    req=requirement,
                    dist=resolved_distribution,
                    discarded=", ".join(
                        str(ranked_dist.distribution) for ranked_dist in available_distributions[1:]
                    ),
                ),
                V=9,
            )

        for dep_requirement in dist_metadata.requires_dists(resolved_distribution):
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

        resolved_dists_by_key.update(
            (key, resolved_distribution) for key in requirement_key.satisfied_keys()
        )

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
        qualified_reqs_by_key = OrderedDict()  # type: OrderedDict[str, List[_QualifiedRequirement]]
        for req in reqs:
            required = self._evaluate_marker(req)
            if required is False:
                continue
            requirements = qualified_reqs_by_key.get(req.key)
            if requirements is None:
                qualified_reqs_by_key[req.key] = requirements = []
            requirements.append(_QualifiedRequirement.create(req, required=required))

        # Next, from among the remaining applicable requirements for a given project, we want to
        # select the most tailored (highest ranked) available distribution. That distribution's
        # transitive requirements will later fill in the full resolve.
        for key, qualified_requirements in qualified_reqs_by_key.items():
            ranked_dists = self._available_ranked_dists_by_key.get(key)
            if ranked_dists is None:
                # We've winnowed down reqs_by_key to just those requirements whose environment
                # markers apply; so, we should always have an available distribution.
                raise ResolveError(
                    "A distribution for {} could not be resolved in this environment.".format(key)
                )
            candidates = [
                (ranked_dist, qualified_requirement)
                for qualified_requirement in qualified_requirements
                for ranked_dist in ranked_dists
                if ranked_dist.satisfies(qualified_requirement.requirement)
            ]
            if not candidates:
                for qualified_requirement in qualified_requirements:
                    yield _DistributionNotFound.create(qualified_requirement.requirement)
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

    def resolve(self, reqs):
        # type: (Iterable[Requirement]) -> Iterable[Distribution]

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

        resolved_dists_by_key = OrderedDict()  # type: OrderedDict[_RequirementKey, Distribution]
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
                    contains = self._available_ranked_dists_by_key[requirement.key]
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

        is_zipped_pex = os.path.isfile(self._pex)
        if not self._pex_info.zip_safe and is_zipped_pex:
            explode_dir = self._force_local()
            # Force subsequent imports to come from the exploded .pex directory rather than the
            # .pex file.
            TRACER.log("Adding exploded non zip-safe pex to the head of sys.path: %s" % explode_dir)
            sys.path[:] = [path for path in sys.path if self._pex != os.path.realpath(path)]
            sys.path.insert(0, explode_dir)
            self._update_module_paths()
        elif not any(self._pex == os.path.realpath(path) for path in sys.path):
            TRACER.log(
                "Adding pex %s to the head of sys.path: %s"
                % ("file" if is_zipped_pex else "dir", self._pex)
            )
            sys.path.insert(0, self._pex)

        all_reqs = [Requirement.parse(req) for req in self._pex_info.requirements]
        resolved = self.resolve(all_reqs)
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
