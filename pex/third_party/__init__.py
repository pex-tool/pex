# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import importlib
import os
import re
import sys

import warnings
import zipfile
from collections import namedtuple, OrderedDict


# NB: All pex imports are performed lazily to play well with the un-imports performed by both the
# PEX runtime when it demotes the bootstrap code and any pex modules that uninstalled
# VendorImporters un-import.
def _tracer():
  from pex.tracer import TRACER

  return TRACER


class _Loader(namedtuple('_Loader', ['module_name', 'vendor_module_name'])):

  # The PEP-302 loader API.
  # See: https://www.python.org/dev/peps/pep-0302/#specification-part-1-the-importer-protocol
  def load_module(self, fullname):
    assert fullname in (self.module_name, self.vendor_module_name), (
      '{} got an unexpected module {}'.format(self, fullname)
    )
    vendored_module = importlib.import_module(self.vendor_module_name)
    sys.modules[fullname] = vendored_module
    _tracer().log('{} imported via {}'.format(fullname, self), V=9)
    return vendored_module

  def unload(self):
    for mod in (self.module_name, self.vendor_module_name):
      if mod in sys.modules:
        sys.modules.pop(mod)
        _tracer().log('un-imported {}'.format(mod), V=9)

        submod_prefix = mod + '.'
        for submod in sorted(m for m in sys.modules.keys() if m.startswith(submod_prefix)):
          sys.modules.pop(submod)
          _tracer().log('un-imported {}'.format(submod), V=9)


class _Importable(namedtuple('_Importable', ['module', 'is_pkg', 'path', 'prefix'])):
  _exposed = False  # noqa: We want instance variable access defaulting to cls here.

  def expose(self):
    self._exposed = True
    importlib.import_module(self.module)
    _tracer().log('Exposed {}'.format(self), V=3)

  def loader_for(self, fullname):
    if fullname.startswith(self.prefix + '.'):
      target = fullname[len(self.prefix + '.'):]
    else:
      if not self._exposed:
        return None
      target = fullname

    if target == self.module or self.is_pkg and target.startswith(self.module + '.'):
      vendor_path = os.path.join(self.path, *target.split('.'))
      vendor_module_name = vendor_path.replace(os.sep, '.')
      return _Loader(fullname, vendor_module_name)


class _DirIterator(namedtuple('_DirIterator', ['rootdir'])):
  def iter_root_modules(self, relpath):
    for entry in self._iter_root(relpath):
      if os.path.isfile(entry):
        name, ext = os.path.splitext(os.path.basename(entry))
        if ext == '.py' and name != '__init__':
          yield name

  def iter_root_packages(self, relpath):
    for entry in self._iter_root(relpath):
      if os.path.isfile(os.path.join(entry, '__init__.py')):
        yield os.path.basename(entry)

  def _iter_root(self, relpath):
    root = os.path.join(self.rootdir, relpath)
    if not os.path.isdir(root):
      # We have nothing at this relpath as can happen when vendoring subsets of pex into its
      # runtime; ie: .bootstrap/pex gets pkg_resources but no setuptools or wheel.
      return

    for entry in os.listdir(root):
      yield os.path.join(root, entry)


class _ZipIterator(namedtuple('_ZipIterator', ['zipfile_path', 'prefix'])):
  @classmethod
  def containing(cls, root):
    prefix = ''
    path = root
    while path:
      if zipfile.is_zipfile(path):
        return cls(zipfile_path=path, prefix=prefix + os.sep if prefix else '')
      prefix = os.path.join(prefix, os.path.basename(path))
      path = os.path.dirname(path)
    raise ValueError('Could not find the zip file housing {}'.format(root))

  def iter_root_modules(self, relpath):
    for package in self._filter_names(relpath, r'(?P<module>[^/]+)\.py', 'module'):
      if package != '__init__':
        yield package

  def iter_root_packages(self, relpath):
    for package in self._filter_names(relpath, r'(?P<package>[^/]+)/__init__\.py', 'package'):
      yield package

  def _filter_names(self, relpath, pattern, group):
    pat = re.compile(r'^{prefix}{pattern}$'
                     .format(prefix=self.prefix + ((relpath + os.sep) if relpath else ''),
                             pattern=pattern))

    with contextlib.closing(zipfile.ZipFile(self.zipfile_path)) as zf:
      for name in zf.namelist():
        match = pat.match(name)
        if match:
          yield match.group(group)


class VendorImporter(object):
  """A `PEP-302 <https://www.python.org/dev/peps/pep-0302/>`_ meta_path importer for vendored code.

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
  def _abs_root(root=None):
    from pex import vendor

    return os.path.abspath(root or vendor.VendorSpec.ROOT)

  @classmethod
  def _iter_importables(cls, root, path_items, prefix):
    module_iterator = _DirIterator(root) if os.path.isdir(root) else _ZipIterator.containing(root)
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
  def _iter_installed_vendor_importers(cls, prefix, root, path_items):
    for importer in cls._iter_all_installed_vendor_importers():
      # All Importables for a given VendorImporter will have the same prefix.
      if importer._importables and importer._importables[0].prefix == prefix:
        if importer._root == root:
          if {importable.path for importable in importer._importables} == set(path_items):
            yield importer

  @classmethod
  def install_vendored(cls, prefix, root=None, expose=None):
    """Install an importer for all vendored code with the given import prefix.

    All distributions listed in ``expose`` will also be made available for import in direct,
    un-prefixed form.

    :param str prefix: The import prefix the installed importer will be responsible for.
    :param str root: The root path of the distribution containing the vendored code. NB: This is the
                     the path to the pex code, which serves as the root under which code is vendored
                     at ``pex/vendor/_vendored``.
    :param expose: Optional names of distributions to expose for direct, un-prefixed import.
    :type expose: list of str
    :raise: :class:`ValueError` if any distributions to expose cannot be found.
    """
    from pex import vendor

    root = cls._abs_root(root)
    vendored_path_items = [spec.relpath for spec in vendor.iter_vendor_specs()]

    installed = list(cls._iter_installed_vendor_importers(prefix, root, vendored_path_items))
    assert len(installed) <= 1, (
      'Unexpected extra importers installed for vendored code:\n\t{}'
        .format('\n\t'.join(map(str, installed)))
    )
    if installed:
      vendor_importer = installed[0]
    else:
      # Install all vendored code for pex internal access to it through the vendor import `prefix`.
      vendor_importer = cls.install(uninstallable=True,
                                    prefix=prefix,
                                    path_items=vendored_path_items,
                                    root=root)

    if expose:
      # But only expose the bits needed.
      path_by_key = OrderedDict((spec.key, spec.relpath) for spec in vendor.iter_vendor_specs()
                                if spec.key in expose)
      path_by_key['pex'] = root  # The pex distribution itself is trivially available to expose.

      unexposed = set(expose) - set(path_by_key.keys())
      if unexposed:
        raise ValueError('The following vendored dists are not available to expose: {}'
                         .format(', '.join(sorted(unexposed))))

      exposed_paths = path_by_key.values()
      for exposed_path in exposed_paths:
        sys.path.insert(0, os.path.join(root, exposed_path))
      vendor_importer._expose(exposed_paths)

  @classmethod
  def install(cls, uninstallable, prefix, path_items, root=None, warning=None):
    """Install an importer for modules found under ``path_items`` at the given import ``prefix``.

    :param bool uninstallable: ``True`` if the installed importer should be uninstalled and any
                               imports it performed be un-imported when ``uninstall`` is called.
    :param str prefix: The import prefix the installed importer will be responsible for.
    :param path_items: The paths relative to ``root`` containing modules to expose for import under
                       ``prefix``.
    :param str root: The root path of the distribution containing the vendored code. NB: This is the
                     the path to the pex code, which serves as the root under which code is vendored
                     at ``pex/vendor/_vendored``.
    :param str warning: An optional warning to emit if any imports are made through the installed
                        importer.
    :return:
    """
    root = cls._abs_root(root)
    importables = tuple(cls._iter_importables(root=root, path_items=path_items, prefix=prefix))
    vendor_importer = cls(root=root,
                          importables=importables,
                          uninstallable=uninstallable,
                          warning=warning)
    if warning:
      warnings.filterwarnings('default', category=DeprecationWarning, module=__name__)
    sys.meta_path.insert(0, vendor_importer)
    _tracer().log('Installed {}'.format(vendor_importer), V=3)
    return vendor_importer

  @classmethod
  def uninstall_all(cls):
    """Uninstall all uninstallable VendorImporters and unimport the modules they loaded."""
    for vendor_importer in cls._iter_all_installed_vendor_importers():
      vendor_importer.uninstall()

  def __init__(self, root, importables, uninstallable=True, warning=None):
    self._root = root
    self._importables = importables

    self._uninstallable = uninstallable
    self._warning = warning

    self._loaders = []

  def uninstall(self):
    """Uninstall this importer if possible and un-import any modules imported by it."""
    if not self._uninstallable:
      _tracer().log('Not uninstalling {}'.format(self), V=9)
      return

    if self in sys.meta_path:
      sys.meta_path.remove(self)
      maybe_exposed = frozenset(os.path.join(self._root, importable.path)
                                for importable in self._importables)
      sys.path[:] = [path_item for path_item in sys.path if path_item not in maybe_exposed]
      for loader in self._loaders:
        loader.unload()
      _tracer().log('Uninstalled {}'.format(self), V=3)

  # The PEP-302 finder API.
  # See: https://www.python.org/dev/peps/pep-0302/#specification-part-1-the-importer-protocol
  def find_module(self, fullname, path=None):
    for importable in self._importables:
      loader = importable.loader_for(fullname)
      if loader is not None:
        self._loaders.append(loader)
        if self._warning:
          warnings.warn('Found loader for `import {}`:\n\t{}'.format(fullname, self._warning),
                        category=DeprecationWarning)
        return loader
    return None

  def _expose(self, paths):
    for importable in self._importables:
      if importable.path in paths:
        importable.expose()

  def __repr__(self):
    return ('{classname}(root={root!r}, importables={importables!r})'
            .format(classname=self.__class__.__name__,
                    root=self._root,
                    importables=self._importables))


_ISOLATED = None


def isolated():
  """Returns a chroot for third_party isolated from the ``sys.path``.

  PEX will typically be installed in site-packages flat alongside many other distributions; as such,
  adding the location of the pex distribution to the ``sys.path`` will typically expose many other
  distributions. An isolated chroot can be used as a ``sys.path`` entry to effect only the exposure
  of pex.

  :return: The path of the chroot.
  :rtype: str
  """
  global _ISOLATED
  if _ISOLATED is None:
    from pex import vendor
    from pex.common import safe_mkdtemp, Chroot

    chroot = Chroot(safe_mkdtemp())
    with _tracer().timed('Isolating pex in {}'.format(chroot)):
      pex_path = os.path.join(vendor.VendorSpec.ROOT, 'pex')
      for root, _, files in os.walk(pex_path):
        for f in files:
          if not f.endswith('.pyc'):
            abs_file_path = os.path.join(root, f)
            relpath = os.path.relpath(abs_file_path, pex_path)
            chroot.copy(abs_file_path, os.path.join('pex', relpath), label='pex')

    _ISOLATED = chroot
  return _ISOLATED.path()


def uninstall():
  """Uninstall all uninstallable :class:`VendorImporter`s and uninmport the modules they loaded."""
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
  <module 'pkg_resources' from '/home/jsirois/dev/pantsbuild/jsirois-pex/.tox/py27-repl/lib/python2.7/site-packages/pkg_resources/__init__.pyc'>  # noqa
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


# Implicitly install an importer for vendored code on the first import of pex.third_party.
install()
