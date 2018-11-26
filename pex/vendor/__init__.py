# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import collections
import os

from pex.common import touch
from pex.tracer import TRACER


_PACKAGE_COMPONENTS = __name__.split('.')


def _root():
  path = os.path.dirname(os.path.abspath(__file__))
  for _ in _PACKAGE_COMPONENTS:
    path = os.path.dirname(path)
  return path


class VendorSpec(collections.namedtuple('VendorSpec', ['key', 'version'])):
  """Represents a vendored distribution.

  NB: Vendored distributions should comply with the host distribution platform constraints. In the
  case of pex, which is a py2.py3 platform agnostic wheel, vendored libraries should be as well.
  """

  ROOT = _root()

  @classmethod
  def create(cls, requirement):
    components = requirement.rsplit('==', 1)
    if len(components) != 2:
      raise ValueError('Vendored requirements must be pinned, given {!r}'.format(requirement))
    key, version = tuple(c.strip() for c in components)
    return cls(key=key, version=version)

  @property
  def _subpath_components(self):
    return ['_vendored', self.key]

  @property
  def relpath(self):
    return os.path.join(*(_PACKAGE_COMPONENTS + self._subpath_components))

  @property
  def target_dir(self):
    return os.path.join(self.ROOT, self.relpath)

  @property
  def requirement(self):
    return '{}=={}'.format(self.key, self.version)

  def create_packages(self):
    """Create missing packages joining the vendor root to the base of the vendored distribution.

    For example, given a root at ``/home/jake/dev/pantsbuild/pex`` and a vendored distribution at
    ``pex/vendor/_vendored/requests`` this method would create the following package files::

      pex/vendor/_vendored/__init__.py
      pex/vendor/_vendored/requests/__init__.py

    These package files allow for standard python importers to find vendored code via re-directs
    from a `PEP-302 <https://www.python.org/dev/peps/pep-0302/>`_ importer like
    :class:`pex.third_party.VendorImporter`.
    """
    for index, _ in enumerate(self._subpath_components):
      relpath = _PACKAGE_COMPONENTS + self._subpath_components[:index + 1] + ['__init__.py']
      touch(os.path.join(self.ROOT, *relpath))


def iter_vendor_specs(include_wheel=True):
  """Iterate specifications for code vendored by pex.

  :param bool include_wheel: If ``True`` include the vendored wheel spec.
  :return: An iterator over specs of all vendored code optionally including ``wheel``.
  :rtype: :class:`collection.Iterator` of :class:`VendorSpec`
  """
  yield VendorSpec.create('setuptools==40.6.2')
  if include_wheel:
    # We're currently stuck here due to removal of an API we depend on.
    # See: https://github.com/pantsbuild/pex/issues/603
    yield VendorSpec.create('wheel==0.31.1')


def _vendored_dists(include_wheel=True):
  entries = [spec.target_dir for spec in iter_vendor_specs(include_wheel=include_wheel)]

  import pex.third_party.pkg_resources as pkg_resources
  return list(pkg_resources.WorkingSet(entries=entries))


def setup_interpreter(interpreter=None, include_wheel=True):
  """Return an interpreter configured with vendored distributions as extras.

  :param interpreter: An option interpreter to configure. If ``None``, the current interpreter is
                      used.
  :type interpreter: :class:`pex.interpreter.PythonInterpreter`
  :param bool include_wheel: If ``True`` include the vendored wheel distribution.
  :return: An bare interpreter configured with vendored extras.
  :rtype: :class:`pex.interpreter.PythonInterpreter`
  """
  from pex.interpreter import PythonInterpreter

  interpreter = interpreter or PythonInterpreter.get()
  for dist in _vendored_dists(include_wheel=include_wheel):
    interpreter = interpreter.with_extra(dist.key, dist.version, dist.location)
  return interpreter


def vendor_runtime(chroot, dest_basedir, label, root_module_names):
  """Includes portions of vendored distributions in a chroot.

  The portion to include is selected by root module name. If the module is a file, just it is
  included. If the module represents a package, the package and all its sub-packages are added
  recursively.

  :param chroot: The chroot to add vendored code to.
  :type chroot: :class:`pex.common.Chroot`
  :param str dest_basedir: The prefix to store the vendored code under in the ``chroot``.
  :param str label: The chroot label for the vendored code fileset.
  :param root_module_names: The names of the root vendored modules to include in the chroot.
  :type root_module_names: :class:`collections.Iterable` of str
  :raise: :class:`ValueError` if any of the given ``root_module_names`` could not be found amongst
          the vendored code and added to the chroot.
  """
  vendor_module_names = {root_module_name: False for root_module_name in root_module_names}
  for spec in iter_vendor_specs():
    for root, dirs, files in os.walk(spec.target_dir):
      if root == spec.target_dir:
        dirs[:] = [pkg_name for pkg_name in dirs if pkg_name in vendor_module_names]
        files[:] = [mod_name for mod_name in files if mod_name[:-3] in vendor_module_names]
        vendored_names = dirs + files
        if vendored_names:
          pkg_path = ''
          for pkg in spec.relpath.split(os.sep):
            pkg_path = os.path.join(pkg_path, pkg)
            pkg_file = os.path.join(pkg_path, '__init__.py')
            src = os.path.join(VendorSpec.ROOT, pkg_file)
            dest = os.path.join(dest_basedir, pkg_file)
            chroot.copy(src, dest, label)
          for name in vendored_names:
            vendor_module_names[name] = True
            TRACER.log('Vendoring {} from {} @ {}'.format(name, spec, spec.target_dir), V=3)

      for filename in files:
        if not filename.endswith('.pyc'):  # Sources and data only.
          src = os.path.join(root, filename)
          dest = os.path.join(dest_basedir, spec.relpath, os.path.relpath(src, spec.target_dir))
          chroot.copy(src, dest, label)

  if not all(vendor_module_names.values()):
    raise ValueError('Failed to extract {module_names} from:\n\t{specs}'.format(
      module_names=', '.join(module
                             for module, written in vendor_module_names.items() if not written),
      specs='\n\t'.join('{} @ {}'.format(spec, spec.target_dir) for spec in iter_vendor_specs())))
