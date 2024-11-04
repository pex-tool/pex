# Copyright 2018 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import hashlib
import importlib
import os
import re
import shutil
import sys
import zipfile
from collections import OrderedDict, namedtuple

from pex.common import CopyMode, iter_copytree

# NB: ~All pex imports are performed lazily to play well with the un-imports performed by both the
# PEX runtime when it demotes the bootstrap code and any pex modules that uninstalled
# VendorImporters un-import.
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import Container, Dict, Iterable, Iterator, List, Optional, Tuple

    from pex.cache.dirs import InstalledWheelDir  # noqa
    from pex.interpreter import PythonInterpreter


def _tracer():
    from pex.tracer import TRACER

    return TRACER


class _Loader(namedtuple("_Loader", ["module_name", "vendor_module_name"])):

    # The PEP-302 loader API.
    # See: https://www.python.org/dev/peps/pep-0302/#specification-part-1-the-importer-protocol
    def load_module(self, fullname):
        assert fullname in (
            self.module_name,
            self.vendor_module_name,
        ), "{} got an unexpected module {}".format(self, fullname)
        vendored_module = importlib.import_module(self.vendor_module_name)
        sys.modules[fullname] = vendored_module
        _tracer().log("{} imported via {}".format(fullname, self), V=9)
        return vendored_module

    def unload(self):
        for mod in (self.module_name, self.vendor_module_name):
            if mod in sys.modules:
                sys.modules.pop(mod)
                _tracer().log("un-imported {}".format(mod), V=9)

                submod_prefix = mod + "."
                for submod in sorted(m for m in sys.modules.keys() if m.startswith(submod_prefix)):
                    sys.modules.pop(submod)
                    _tracer().log("un-imported {}".format(submod), V=9)


class _Importable(namedtuple("_Importable", ["module", "is_pkg", "path", "prefix"])):
    _exposed = False  # noqa: We want instance variable access defaulting to cls here.

    def expose(self):
        # type: () -> None
        self._exposed = True
        _tracer().log("Exposed {}".format(self), V=3)

    @property
    def exposed(self):
        # type: () -> bool
        return self._exposed

    def loader_for(self, fullname):
        # type: (str) -> Optional[_Loader]
        if fullname.startswith(self.prefix + "."):
            target = fullname[len(self.prefix + ".") :]
        else:
            if not self._exposed:
                return None
            target = fullname

        if target == self.module or self.is_pkg and target.startswith(self.module + "."):
            vendor_path = (
                os.path.join(*target.split("."))
                if not self.path or self.path == os.curdir
                else os.path.join(self.path, *target.split("."))
            )
            vendor_module_name = vendor_path.replace(os.sep, ".")
            return _Loader(fullname, vendor_module_name)

        return None


class _DirIterator(namedtuple("_DirIterator", ["rootdir"])):
    def iter_root_modules(self, relpath):
        for entry in self._iter_root(relpath):
            if os.path.isfile(entry):
                name, ext = os.path.splitext(os.path.basename(entry))
                if ext == ".py" and name != "__init__":
                    yield name

    def iter_root_packages(self, relpath):
        for entry in self._iter_root(relpath):
            if os.path.isfile(os.path.join(entry, "__init__.py")):
                yield os.path.basename(entry)

    def _iter_root(self, relpath):
        root = os.path.join(self.rootdir, relpath)
        if not os.path.isdir(root):
            # We have nothing at this relpath as can happen when vendoring subsets of pex into its
            # runtime; ie: .bootstrap/pex gets pkg_resources but no setuptools or wheel.
            return

        for entry in os.listdir(root):
            yield os.path.join(root, entry)


class _ZipIterator(namedtuple("_ZipIterator", ["zipfile_path", "prefix"])):
    @classmethod
    def containing(cls, root):
        prefix = ""
        path = root
        while path:
            # We use '/' here because the zip file format spec specifies that paths must use
            # forward slashes. See section 4.4.17 of
            # https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT.
            if zipfile.is_zipfile(path):
                return cls(zipfile_path=path, prefix="{}/".format(prefix) if prefix else "")
            path_base = os.path.basename(path)
            prefix = "{}/{}".format(path_base, prefix) if prefix else path_base
            path = os.path.dirname(path)
        raise ValueError("Could not find the zip file housing {}".format(root))

    def iter_root_modules(self, relpath):
        for package in self._filter_names(relpath, r"(?P<module>[^/]+)\.py", "module"):
            if package != "__init__":
                yield package

    def iter_root_packages(self, relpath):
        for package in self._filter_names(relpath, r"(?P<package>[^/]+)/__init__\.py", "package"):
            yield package

    def _filter_names(self, relpath, pattern, group):
        # We use '/' here because the zip file format spec specifies that paths must use
        # forward slashes. See section 4.4.17 of
        # https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT.
        relpath_pat = "" if not relpath else "{}/".format(relpath.replace(os.sep, "/"))
        pat = re.compile(r"^{}{}{}$".format(self.prefix, relpath_pat, pattern))
        with contextlib.closing(zipfile.ZipFile(self.zipfile_path)) as zf:
            for name in zf.namelist():
                match = pat.match(name)
                if match:
                    yield match.group(group)


class VendorImporter(object):
    """A `PEP-302 <https://www.python.org/dev/peps/pep-0302/>`_ meta_path importer for vendored
    code.

    This importer redirects imports from its package to vendored code, optionally exposing the
    vendored code by its un-prefixed module name as well.

    For example, if the ``requests`` distribution was vendored, it could be imported using this
    importer via ``import pex.third_party.requests`` as long as:

      * The requests distribution was housed under some importable path prefix inside this
        distribution.
      * The requests distribution had its self-referential absolute imports re-written to use the
        vendored import prefix.
    """

    @staticmethod
    def _vendored_path_items():
        # type: () -> Iterable[str]
        from pex import vendor

        return tuple(
            spec.relpath
            for spec in vendor.iter_vendor_specs(
                # N.B.: The VendorImporter should only see the versions of vendored projects that
                # support the current Python interpreter.
                filter_requires_python=sys.version_info[:2]
            )
        )

    @staticmethod
    def _abs_root(root=None):
        # type: (Optional[str]) -> str
        from pex import vendor

        return os.path.abspath(root or vendor.VendorSpec.ROOT)

    @classmethod
    def _iter_importables(cls, root, path_items, prefix):
        module_iterator = (
            _DirIterator(root) if os.path.isdir(root) else _ZipIterator.containing(root)
        )
        for path_item in path_items:
            for module_name in module_iterator.iter_root_modules(path_item):
                yield _Importable(module=module_name, is_pkg=False, path=path_item, prefix=prefix)
            for package_name in module_iterator.iter_root_packages(path_item):
                yield _Importable(module=package_name, is_pkg=True, path=path_item, prefix=prefix)

    @classmethod
    def _iter_all_installed_vendor_importers(cls):
        for importer in sys.meta_path:
            if isinstance(importer, cls):
                yield importer

    @classmethod
    def iter_installed_vendor_importers(
        cls,
        prefix,  # type: str
        root=None,  # type: Optional[str]
    ):
        # type: (...) -> Iterator[VendorImporter]
        root = cls._abs_root(root)
        for importer in cls._iter_all_installed_vendor_importers():
            # All Importables for a given VendorImporter will have the same prefix.
            if importer._importables and importer._importables[0].prefix == prefix:
                if importer._root == root:
                    yield importer

    @classmethod
    def install_vendored(
        cls,
        prefix,  # type: str
        root=None,  # type: Optional[str]
        expose=None,  # type: Optional[Iterable[str]]
    ):
        # type: (...) -> None
        """Install an importer for all vendored code with the given import prefix.

        All distributions listed in ``expose`` will also be made available for import in direct,
        un-prefixed form.

        :param prefix: The import prefix the installed importer will be responsible for.
        :param root: The root path of the distribution containing the vendored code. NB: This is the
                     path to the pex code, which serves as the root under which code is vendored at
                     ``pex/vendor/_vendored``.
        :param expose: Optional names of distributions to expose for direct, un-prefixed import.
        :raise: :class:`ValueError` if any distributions to expose cannot be found.
        """
        root = cls._abs_root(root)
        installed = tuple(cls.iter_installed_vendor_importers(prefix, root=root))
        assert (
            len(installed) <= 1
        ), "Unexpected extra importers installed for vendored code:\n\t{}".format(
            "\n\t".join(map(str, installed))
        )
        if installed:
            vendor_importer = installed[0]
        else:
            # Install all vendored code for pex internal access to it through the vendor import
            # `prefix`.
            vendor_importer = cls.install(
                uninstallable=True, prefix=prefix, path_items=cls._vendored_path_items(), root=root
            )

        if expose:
            # But only expose the bits needed.
            exposed_paths = []
            for path in cls.expose(expose, root):
                sys.path.insert(0, path)
                exposed_paths.append(os.path.relpath(path, root))

            vendor_importer._expose(exposed_paths)

    @classmethod
    def expose(
        cls,
        dists,  # type: Iterable[str]
        root=None,  # type: Optional[str]
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> Iterator[str]
        from pex import vendor

        root = cls._abs_root(root)

        def iter_available():
            yield "pex", root  # The pex distribution itself is trivially available to expose.
            for spec in vendor.iter_vendor_specs(filter_requires_python=interpreter):
                yield spec.key, spec.relpath

        path_by_key = OrderedDict(
            (key, relpath) for key, relpath in iter_available() if key in dists
        )

        unexposed = set(dists) - set(path_by_key.keys())
        if unexposed:
            raise ValueError(
                "The following vendored dists are not available to expose: {}".format(
                    ", ".join(sorted(unexposed))
                )
            )

        exposed_paths = path_by_key.values()
        for exposed_path in exposed_paths:
            yield os.path.join(root, exposed_path)

    @classmethod
    def install(cls, uninstallable, prefix, path_items, root=None):
        """Install an importer for modules found under ``path_items`` at the given import
        ``prefix``.

        :param bool uninstallable: ``True`` if the installed importer should be uninstalled and any
                                   imports it performed be un-imported when ``uninstall`` is called.
        :param str prefix: The import prefix the installed importer will be responsible for.
        :param path_items: The paths relative to ``root`` containing modules to expose for import under
                           ``prefix``.
        :param str root: The root path of the distribution containing the vendored code. NB: This is the
                         the path to the pex code, which serves as the root under which code is vendored
                         at ``pex/vendor/_vendored``.
        :return: The installed importer.
        :rtype: :class:`VendorImporter`
        """
        root = cls._abs_root(root)
        importables = tuple(cls._iter_importables(root=root, path_items=path_items, prefix=prefix))
        vendor_importer = cls(root=root, importables=importables, uninstallable=uninstallable)
        sys.meta_path.insert(0, vendor_importer)
        _tracer().log("Installed {}".format(vendor_importer), V=3)
        return vendor_importer

    @classmethod
    def uninstall_all(cls):
        """Uninstall all uninstallable VendorImporters and unimport the modules they loaded."""
        for vendor_importer in cls._iter_all_installed_vendor_importers():
            vendor_importer.uninstall()

    def __init__(
        self,
        root,  # type: str
        importables,  # type: Tuple[_Importable, ...]
        uninstallable=True,  # type: bool
    ):
        # type: (...) -> None
        self._root = root
        self._importables = importables
        self._uninstallable = uninstallable

        self._loaders = []  # type: List[_Loader]

    @property
    def root(self):
        # type: () -> str
        return self._root

    @property
    def importables(self):
        # type: () -> Iterable[_Importable]
        return self._importables

    def uninstall(self):
        """Uninstall this importer if possible and un-import any modules imported by it."""
        if not self._uninstallable:
            _tracer().log("Not uninstalling {}".format(self), V=9)
            return

        if self in sys.meta_path:
            sys.meta_path.remove(self)
            maybe_exposed = frozenset(
                os.path.join(self._root, importable.path) for importable in self._importables
            )
            sys.path[:] = [path_item for path_item in sys.path if path_item not in maybe_exposed]
            for loader in self._loaders:
                loader.unload()
            _tracer().log("Uninstalled {}".format(self), V=3)

    def find_spec(self, fullname, path, target=None):
        # Python 2.7 does not know about this API and does not use it.
        from importlib.util import spec_from_loader  # type: ignore[import]

        loader = self.find_module(fullname, path)
        if loader:
            return spec_from_loader(fullname, loader)
        return None

    # The Legacy PEP-302 finder API.
    # See: https://www.python.org/dev/peps/pep-0302/#specification-part-1-the-importer-protocol
    def find_module(self, fullname, path=None):
        for importable in self._importables:
            loader = importable.loader_for(fullname)
            if loader is not None:
                self._loaders.append(loader)
                return loader
        return None

    def _expose(self, paths):
        for importable in self._importables:
            if importable.path in paths:
                importable.expose()

    def __repr__(self):
        return "{classname}(root={root!r}, importables={importables!r})".format(
            classname=self.__class__.__name__, root=self._root, importables=self._importables
        )


class IsolationResult(namedtuple("IsolatedPex", ["pex_hash", "chroot_path"])):
    """The result of isolating the current pex distribution to a filesystem chroot."""


# We use this to isolate Pex installations by PEX_ROOT for tests. In production, there will only
# ever be 1 PEX_ROOT per Pex process lifetime.
_ISOLATED = {}  # type: Dict[str, Optional[IsolationResult]]


def _isolate_pex_from_dir(
    pex_directory,  # type: str
    isolate_to_dir,  # type: str
    exclude_files,  # type: Container[str]
):
    # type: (...) -> None
    from pex.common import is_pyc_dir, is_pyc_file, is_pyc_temporary_file, safe_copy

    for root, dirs, files in os.walk(pex_directory):
        relroot = os.path.relpath(root, pex_directory)
        for d in dirs:
            if is_pyc_dir(d):
                continue
            os.makedirs(os.path.join(isolate_to_dir, "pex", relroot, d))
        for f in files:
            if is_pyc_file(f):
                continue
            rel_f = os.path.join(relroot, f)
            if not is_pyc_temporary_file(rel_f) and rel_f not in exclude_files:
                safe_copy(
                    os.path.join(root, f),
                    os.path.join(isolate_to_dir, "pex", rel_f),
                )


def _isolate_pex_from_zip(
    pex_zip,  # type: str
    pex_package_relpath,  # type: str
    isolate_to_dir,  # type: str
    exclude_files,  # type: Container[str]
):
    # type: (...) -> None
    from pex.common import open_zip, safe_open

    with open_zip(pex_zip) as zf:
        for name in zf.namelist():
            if name.endswith("/") or not name.startswith(pex_package_relpath):
                continue
            rel_name = os.path.relpath(name, pex_package_relpath)
            if rel_name in exclude_files:
                continue
            with zf.open(name) as from_fp, safe_open(
                os.path.join(isolate_to_dir, rel_name), "wb"
            ) as to_fp:
                shutil.copyfileobj(from_fp, to_fp)


def isolated(interpreter=None):
    # type: (Optional[PythonInterpreter]) -> IsolationResult
    """Returns a chroot for third_party isolated from the ``sys.path``.

    PEX will typically be installed in site-packages flat alongside many other distributions; as such,
    adding the location of the pex distribution to the ``sys.path`` will typically expose many other
    distributions. An isolated chroot can be used as a ``sys.path`` entry to effect only the exposure
    of pex.

    :return: An isolation result.
    """
    from pex.variables import ENV

    pex_root = ENV.PEX_ROOT
    isolation_result = _ISOLATED.get(pex_root)
    if isolation_result is None:
        from pex import layout, vendor
        from pex.atomic_directory import atomic_directory
        from pex.cache.dirs import CacheDir
        from pex.util import CacheHelper

        module = "pex"

        # These files are only used for running `tox -evendor` and should not pollute either the
        # PEX_ROOT or built PEXs.
        vendor_lockfiles = tuple(
            os.path.join(os.path.relpath(vendor_spec.relpath, module), "constraints.txt")
            for vendor_spec in vendor.iter_vendor_specs(filter_requires_python=interpreter)
        )

        pex_zip_paths = None  # type: Optional[Tuple[str, str]]
        pex_path = os.path.join(vendor.VendorSpec.ROOT, "pex")
        with _tracer().timed("Hashing pex"):
            if os.path.isdir(pex_path):
                pex_hash = CacheHelper.dir_hash(pex_path)
            else:
                # The zip containing the `pex` package could either be a traditional PEX zipapp
                # with the `pex` package in `.bootstrap/pex` or a .bootstrap zip with the `pex`
                # package in the root of the zip. We deal with both cases below.
                zip_path = os.path.dirname(pex_path)
                if (
                    not zipfile.is_zipfile(zip_path)
                    and os.path.basename(zip_path) == layout.BOOTSTRAP_DIR
                ):
                    zip_path = os.path.dirname(zip_path)
                assert zipfile.is_zipfile(zip_path), (
                    "Expected the `pex` module to be available via an installed distribution "
                    "or else via a PEX. Loaded the `pex` module from {} and but the enclosing "
                    "PEX has an unexpected layout {}".format(pex_path, zip_path)
                )

                pex_package_relpath = (
                    ""
                    if os.path.basename(zip_path) == layout.BOOTSTRAP_DIR
                    else layout.BOOTSTRAP_DIR
                )
                pex_zip_paths = (zip_path, pex_package_relpath)
                pex_hash = CacheHelper.zip_hash(zip_path, relpath=pex_package_relpath)

        isolated_dir = CacheDir.ISOLATED.path(pex_hash, pex_root=pex_root)
        with _tracer().timed("Isolating pex"):
            with atomic_directory(isolated_dir) as chroot:
                if not chroot.is_finalized():
                    with _tracer().timed("Extracting pex to {}".format(isolated_dir)):
                        if pex_zip_paths:
                            pex_zip, pex_package_relpath = pex_zip_paths
                            _isolate_pex_from_zip(
                                pex_zip=pex_zip,
                                pex_package_relpath=pex_package_relpath,
                                isolate_to_dir=chroot.work_dir,
                                exclude_files=vendor_lockfiles,
                            )
                        else:
                            _isolate_pex_from_dir(
                                pex_directory=pex_path,
                                isolate_to_dir=chroot.work_dir,
                                exclude_files=vendor_lockfiles,
                            )

        isolation_result = IsolationResult(pex_hash=pex_hash, chroot_path=isolated_dir)
        _ISOLATED[pex_root] = isolation_result
    return isolation_result


def uninstall():
    """Uninstall all uninstallable :class:`VendorImporter`s and uninmport the modules they
    loaded."""
    VendorImporter.uninstall_all()


def import_prefix():
    """Returns the vendoring import prefix; eg: `pex.third_party`.

    :rtype: str
    """
    return __name__


def install(root=None, expose=None):
    """Installs the default :class:`VendorImporter` for PEX vendored code.

    Any distributions listed in ``expose`` will also be exposed for direct import; ie:
    ``install(expose=['setuptools'])`` would make both ``setuptools`` and ``wheel`` available for
    import via ``from  pex.third_party import setuptools, wheel``, but only ``setuptools`` could be
    directly imported via ``import setuptools``.

    NB: Even when exposed, vendored code is not the same as the same un-vendored code and will
    properly fail type-tests against un-vendored types. For example, in an interpreter that has
    ``setuptools`` installed in its site-packages:

    >>> from pkg_resources import Requirement
    >>> orig_req = Requirement.parse('wheel==0.31.1')
    >>> from pex import third_party
    >>> third_party.install(expose=['setuptools'])
    >>> import sys
    >>> sys.modules.pop('pkg_resources')
    <module 'pkg_resources' from '/home/jsirois/dev/pex-tool/pex/.tox/py27-repl/lib/python2.7/site-packages/pkg_resources/__init__.pyc'>  # noqa
    >>> from pkg_resources import Requirement
    >>> new_req = Requirement.parse('wheel==0.31.1')
    >>> new_req == orig_req
    False
    >>> new_req == Requirement.parse('wheel==0.31.1')
    True
    >>> type(orig_req)
    <class 'pkg_resources.Requirement'>
    >>> type(new_req)
    <class 'pex.vendor._vendored.setuptools.pkg_resources.Requirement'>
    >>> from pex.third_party.pkg_resources import Requirement as PrefixedRequirement
    >>> new_req == PrefixedRequirement.parse('wheel==0.31.1')
    True
    >>> sys.modules.pop('pkg_resources')
    <module 'pex.vendor._vendored.setuptools.pkg_resources' from 'pex/vendor/_vendored/setuptools/pkg_resources/__init__.pyc'>  # noqa
    >>> sys.modules.pop('pex.third_party.pkg_resources')
    <module 'pex.vendor._vendored.setuptools.pkg_resources' from 'pex/vendor/_vendored/setuptools/pkg_resources/__init__.pyc'>  # noqa
    >>>

    :param expose: A list of vendored distribution names to expose directly on the ``sys.path``.
    :type expose: list of str
    :raise: :class:`ValueError` if any distributions to expose cannot be found.
    """
    VendorImporter.install_vendored(prefix=import_prefix(), root=root, expose=expose)


def exposed(root=None):
    # type: (Optional[str]) -> Iterator[str]
    """Returns the ``sys.path`` entries of distributions that have been exposed."""
    for importer in VendorImporter.iter_installed_vendor_importers(
        prefix=import_prefix(), root=root
    ):
        for importable in importer.importables:
            if importable.exposed:
                yield os.path.join(importer.root, importable.path)


def expose(
    dists,  # type: Iterable[str]
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> Iterator[str]
    """Exposes vendored code in isolated chroots.

    Any vendored distributions listed in ``dists`` will be unpacked to individual chroots for
    addition to the ``sys.path``; ie: ``expose(['setuptools', 'wheel'])`` will unpack these vendored
    distributions and yield the two chroot paths they were unpacked to.

    :param dists: A sequence of vendored distribution names to expose.
    :param interpreter: The target interpreter to expose dists for. The current interpreter by
                        default.
    :raise: :class:`ValueError` if any distributions to expose cannot be found.
    :returns: An iterator of exposed vendored distribution chroot paths.
    """
    for path in VendorImporter.expose(dists, root=isolated().chroot_path, interpreter=interpreter):
        yield path


def expose_installed_wheels(
    dists,  # type: Iterable[str]
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> Iterator[InstalledWheelDir]

    from pex.atomic_directory import atomic_directory
    from pex.cache.dirs import InstalledWheelDir
    from pex.pep_376 import InstalledWheel

    for path in expose(dists, interpreter=interpreter):
        # TODO(John Sirois): Maybe consolidate with pex.resolver.BuildAndInstallRequest.
        #  https://github.com/pex-tool/pex/issues/2556
        installed_wheel = InstalledWheel.load(path)
        wheel_file_name = installed_wheel.wheel_file_name()
        install_hash = installed_wheel.fingerprint or CacheHelper.dir_hash(
            path, hasher=hashlib.sha256
        )
        installed_wheel_dir = InstalledWheelDir.create(
            wheel_name=wheel_file_name, install_hash=install_hash
        )
        with atomic_directory(installed_wheel_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                for _src, _dst in iter_copytree(path, atomic_dir.work_dir, copy_mode=CopyMode.LINK):
                    pass
        yield installed_wheel_dir


# Implicitly install an importer for vendored code on the first import of pex.third_party.
# N.B.: attrs must be exposed to make use of `cache_hash=True` since that generates and compiles
# code on the fly that generated code does a bare `import attr`.
install(expose=["attrs"])
