# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import importlib
import itertools
import os
import site
import sys
import zipfile
from collections import OrderedDict, defaultdict

from pex import dist_metadata, pex_builder, pex_warnings
from pex.bootstrap import Bootstrap
from pex.common import atomic_directory, die, open_zip
from pex.inherit_path import InheritPath
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.third_party.packaging import tags
from pex.third_party.pkg_resources import DistributionNotFound, Environment, Requirement, WorkingSet
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper, DistributionHelper

if TYPE_CHECKING:
    from typing import Optional


def _import_pkg_resources():
    try:
        import pkg_resources  # vendor:skip

        return pkg_resources, False
    except ImportError:
        from pex import third_party

        third_party.install(expose=["setuptools"])
        import pkg_resources  # vendor:skip

        return pkg_resources, True


class PEXEnvironment(Environment):
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

    @classmethod
    def _force_local(cls, pex_file, pex_info):
        if pex_info.code_hash is None:
            # Do not support force_local if code_hash is not set. (It should always be set.)
            return pex_file
        explode_dir = os.path.join(pex_info.zip_unsafe_cache, pex_info.code_hash)
        TRACER.log("PEX is not zip safe, exploding to %s" % explode_dir)
        with atomic_directory(explode_dir, exclusive=True) as explode_tmp:
            if explode_tmp:
                with TRACER.timed("Unzipping %s" % pex_file):
                    with open_zip(pex_file) as pex_zip:
                        pex_files = (
                            x
                            for x in pex_zip.namelist()
                            if not x.startswith(pex_builder.BOOTSTRAP_DIR)
                            and not x.startswith(pex_info.internal_cache)
                        )
                        pex_zip.extractall(explode_tmp, pex_files)
        return explode_dir

    @classmethod
    def _update_module_paths(cls, pex_file):
        bootstrap = Bootstrap.locate()

        # Un-import any modules already loaded from within the .pex file.
        to_reimport = []
        for name, module in reversed(sorted(sys.modules.items())):
            if bootstrap.imported_from_bootstrap(module):
                TRACER.log("Not re-importing module %s from bootstrap." % module, V=3)
                continue

            pkg_path = getattr(module, "__path__", None)
            if pkg_path and any(
                os.path.realpath(path_item).startswith(pex_file) for path_item in pkg_path
            ):
                sys.modules.pop(name)
                to_reimport.append((name, pkg_path, True))
            elif (
                name != "__main__"
            ):  # The __main__ module is special in python and is not re-importable.
                mod_file = getattr(module, "__file__", None)
                if mod_file and os.path.realpath(mod_file).startswith(pex_file):
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

    @classmethod
    def _write_zipped_internal_cache(cls, zf, pex_info):
        cached_distributions = []
        for distribution_name, dist_digest in pex_info.distributions.items():
            internal_dist_path = "/".join([pex_info.internal_cache, distribution_name])
            cached_location = os.path.join(pex_info.install_cache, dist_digest, distribution_name)
            dist = CacheHelper.cache_distribution(zf, internal_dist_path, cached_location)
            cached_distributions.append(dist)
        return cached_distributions

    @classmethod
    def _load_internal_cache(cls, pex, pex_info):
        """Possibly cache out the internal cache."""
        internal_cache = os.path.join(pex, pex_info.internal_cache)
        with TRACER.timed("Searching dependency cache: %s" % internal_cache, V=2):
            if len(pex_info.distributions) == 0:
                # We have no .deps to load.
                return

            if os.path.isdir(pex):
                search_path = [
                    os.path.join(internal_cache, dist_chroot)
                    for dist_chroot in os.listdir(internal_cache)
                ]
                internal_env = Environment(search_path=search_path)
                for dist_name in internal_env:
                    for dist in internal_env[dist_name]:
                        yield dist
            else:
                with open_zip(pex) as zf:
                    for dist in cls._write_zipped_internal_cache(zf, pex_info):
                        yield dist

    def __init__(self, pex, pex_info, interpreter=None):
        # type: (str, PexInfo, Optional[PythonInterpreter]) -> None
        self._internal_cache = os.path.join(pex, pex_info.internal_cache)
        self._pex = pex
        self._pex_info = pex_info
        self._activated = False
        self._working_set = None
        self._interpreter = interpreter or PythonInterpreter.get()
        self._inherit_path = pex_info.inherit_path
        self._supported_tags = frozenset(self._interpreter.identity.supported_tags)
        self._target_interpreter_env = self._interpreter.identity.env_markers

        # For the bug this works around, see: https://bitbucket.org/pypy/pypy/issues/1686
        # NB: This must be installed early before the underlying pex is loaded in any way.
        if self._interpreter.identity.python_tag.startswith("pp") and zipfile.is_zipfile(self._pex):
            self._install_pypy_zipimporter_workaround(self._pex)

        super(PEXEnvironment, self).__init__(
            search_path=[] if pex_info.inherit_path == InheritPath.FALSE else sys.path,
            platform=self._interpreter.identity.platform_tag,
        )
        TRACER.log(
            "E: tags for %r x %r -> %s" % (self.platform, self._interpreter, self._supported_tags),
            V=9,
        )

    def _update_candidate_distributions(self, distribution_iter):
        for dist in distribution_iter:
            if self.can_add(dist):
                with TRACER.timed("Adding %s" % dist, V=2):
                    self.add(dist)

    def can_add(self, dist):
        filename, ext = os.path.splitext(os.path.basename(dist.location))
        if ext.lower() != ".whl":
            # This supports resolving pex's own vendored distributions which are vendored in directory
            # directory with the project name (`pip/` for pip) and not the corresponding wheel name
            # (`pip-19.3.1-py2.py3-none-any.whl/` for pip). Pex only vendors universal wheels for all
            # platforms it supports at buildtime and runtime so this is always safe.
            return True

        # Wheel filename format: https://www.python.org/dev/peps/pep-0427/#file-name-convention
        # `{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl`
        wheel_components = filename.split("-")
        if len(wheel_components) < 3:
            return False

        wheel_tags = "-".join(wheel_components[-3:])  # `{python tag}-{abi tag}-{platform tag}`
        if self._supported_tags.isdisjoint(tags.parse_tag(wheel_tags)):
            return False

        python_requires = dist_metadata.requires_python(dist)
        if not python_requires:
            return True

        return self._interpreter.identity.version_str in python_requires

    def activate(self):
        if not self._activated:
            with TRACER.timed("Activating PEX virtual environment from %s" % self._pex):
                self._working_set = self._activate()
            self._activated = True

        return self._working_set

    def _resolve(self, working_set, reqs):
        environment = self._target_interpreter_env.copy()
        environment["extra"] = list(set(itertools.chain(*(req.extras for req in reqs))))

        reqs_by_key = OrderedDict()
        for req in reqs:
            if req.marker and not req.marker.evaluate(environment=environment):
                TRACER.log(
                    "Skipping activation of `%s` due to environment marker de-selection" % req
                )
                continue
            reqs_by_key.setdefault(req.key, []).append(req)

        unresolved_reqs = OrderedDict()
        resolveds = OrderedSet()

        # Resolve them one at a time so that we can figure out which ones we need to elide should
        # there be an interpreter incompatibility.
        for key, reqs in reqs_by_key.items():
            with TRACER.timed("Resolving {} from {}".format(key, reqs), V=2):
                # N.B.: We resolve the bare requirement with no version specifiers since the resolve process
                # used to build this pex already did so. There may be multiple distributions satisfying any
                # particular key (e.g.: a Python 2 specific version and a Python 3 specific version for a
                # multi-python PEX) and we want the working set to pick the most appropriate one.
                req = Requirement.parse(key)
                try:
                    resolveds.update(working_set.resolve([req], env=self))
                except DistributionNotFound as e:
                    TRACER.log("Failed to resolve a requirement: %s" % e)
                    requirers = unresolved_reqs.setdefault(e.req, OrderedSet())
                    if e.requirers:
                        for requirer in e.requirers:
                            requirers.update(reqs_by_key[requirer])

        if unresolved_reqs:
            TRACER.log("Unresolved requirements:")
            for req in unresolved_reqs:
                TRACER.log("  - %s" % req)

            TRACER.log("Distributions contained within this pex:")
            distributions_by_key = defaultdict(list)
            if not self._pex_info.distributions:
                TRACER.log("  None")
            else:
                for dist_name, dist_digest in self._pex_info.distributions.items():
                    TRACER.log("  - %s" % dist_name)
                    distribution = DistributionHelper.distribution_from_path(
                        path=os.path.join(self._pex_info.install_cache, dist_digest, dist_name)
                    )
                    distributions_by_key[distribution.as_requirement().key].append(distribution)

            if not self._pex_info.ignore_errors:
                items = []
                for index, (requirement, requirers) in enumerate(unresolved_reqs.items()):
                    rendered_requirers = ""
                    if requirers:
                        rendered_requirers = ("\n    Required by:" "\n      {requirers}").format(
                            requirers="\n      ".join(map(str, requirers))
                        )

                    items.append(
                        "{index: 2d}: {requirement}"
                        "{rendered_requirers}"
                        "\n    But this pex only contains:"
                        "\n      {distributions}".format(
                            index=index + 1,
                            requirement=requirement,
                            rendered_requirers=rendered_requirers,
                            distributions="\n      ".join(
                                os.path.basename(d.location)
                                for d in distributions_by_key[requirement.key]
                            ),
                        )
                    )

                die(
                    "Failed to execute PEX file. Needed {platform} compatible dependencies for:\n{items}".format(
                        platform=self._interpreter.platform, items="\n".join(items)
                    )
                )

        return resolveds

    _NAMESPACE_PACKAGE_METADATA_RESOURCE = "namespace_packages.txt"

    @classmethod
    def _get_namespace_packages(cls, dist):
        if dist.has_metadata(cls._NAMESPACE_PACKAGE_METADATA_RESOURCE):
            return list(dist.get_metadata_lines(cls._NAMESPACE_PACKAGE_METADATA_RESOURCE))
        else:
            return []

    @classmethod
    def declare_namespace_packages(cls, resolved_dists):
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
        # type: () -> WorkingSet
        pex_file = os.path.realpath(self._pex)

        self._update_candidate_distributions(self._load_internal_cache(pex_file, self._pex_info))

        is_zipped_pex = os.path.isfile(pex_file)
        if not self._pex_info.zip_safe and is_zipped_pex:
            explode_dir = self._force_local(pex_file=pex_file, pex_info=self._pex_info)
            # Force subsequent imports to come from the exploded .pex directory rather than the .pex file.
            TRACER.log("Adding exploded non zip-safe pex to the head of sys.path: %s" % explode_dir)
            sys.path[:] = [path for path in sys.path if pex_file != os.path.realpath(path)]
            sys.path.insert(0, explode_dir)
            self._update_module_paths(pex_file=pex_file)
        elif not any(pex_file == os.path.realpath(path) for path in sys.path):
            TRACER.log(
                "Adding pex %s to the head of sys.path: %s"
                % ("file" if is_zipped_pex else "dir", pex_file)
            )
            sys.path.insert(0, pex_file)

        all_reqs = [Requirement.parse(req) for req in self._pex_info.requirements]

        working_set = WorkingSet([])
        resolved = self._resolve(working_set, all_reqs)

        for dist in resolved:
            with TRACER.timed("Activating %s" % dist, V=2):
                working_set.add(dist)

                if self._inherit_path == InheritPath.FALLBACK:
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

        return working_set
