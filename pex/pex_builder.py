# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
import os

from pex.common import Chroot, chmod_plus_x, open_zip, safe_mkdir, safe_mkdtemp
from pex.compatibility import to_bytes
from pex.compiler import Compiler
from pex.finders import get_entry_point_from_console_script, get_script_from_distributions
from pex.interpreter import PythonInterpreter
from pex.pex_info import PexInfo
from pex.third_party.pkg_resources import DefaultProvider, ZipProvider, get_provider
from pex.tracer import TRACER
from pex.util import CacheHelper, DistributionHelper

BOOTSTRAP_DIR = '.bootstrap'

LEGACY_BOOSTRAP_PKG = '_pex'

BOOTSTRAP_ENVIRONMENT = """
import os
import sys

__entry_point__ = None
if '__file__' in locals() and __file__ is not None:
  __entry_point__ = os.path.dirname(__file__)
elif '__loader__' in locals():
  from pkgutil import ImpLoader
  if hasattr(__loader__, 'archive'):
    __entry_point__ = __loader__.archive
  elif isinstance(__loader__, ImpLoader):
    __entry_point__ = os.path.dirname(__loader__.get_filename())

if __entry_point__ is None:
  sys.stderr.write('Could not launch python executable!\\n')
  sys.exit(2)

sys.path[0] = os.path.abspath(sys.path[0])
sys.path.insert(0, os.path.abspath(os.path.join(__entry_point__, {bootstrap_dir!r})))

from pex.third_party import VendorImporter
VendorImporter.install(uninstallable=False,
                       prefix={legacy_bootstrap_pkg!r},
                       path_items=['pex'],
                       warning='Runtime pex API access through the `{legacy_bootstrap_pkg}` '
                               'package is deprecated and will be removed in pex 2.0.0. Please '
                               'switch to the `pex` package for runtime API access.')

from pex.pex_bootstrapper import bootstrap_pex
bootstrap_pex(__entry_point__)
""".format(bootstrap_dir=BOOTSTRAP_DIR, legacy_bootstrap_pkg=LEGACY_BOOSTRAP_PKG)


class PEXBuilder(object):
  """Helper for building PEX environments."""

  class Error(Exception): pass
  class ImmutablePEX(Error): pass
  class InvalidDistribution(Error): pass
  class InvalidDependency(Error): pass
  class InvalidExecutableSpecification(Error): pass

  def __init__(self, path=None, interpreter=None, chroot=None, pex_info=None, preamble=None,
               copy=False):
    """Initialize a pex builder.

    :keyword path: The path to write the PEX as it is built.  If ``None`` is specified,
      a temporary directory will be created.
    :keyword interpreter: The interpreter to use to build this PEX environment.  If ``None``
      is specified, the current interpreter is used.
    :keyword chroot: If specified, preexisting :class:`Chroot` to use for building the PEX.
    :keyword pex_info: A preexisting PexInfo to use to build the PEX.
    :keyword preamble: If supplied, execute this code prior to bootstrapping this PEX
      environment.
    :type preamble: str
    :keyword copy: If False, attempt to create the pex environment via hard-linking, falling
                   back to copying across devices. If True, always copy.

    .. versionchanged:: 0.8
      The temporary directory created when ``path`` is not specified is now garbage collected on
      interpreter exit.
    """
    self._interpreter = interpreter or PythonInterpreter.get()
    self._chroot = chroot or Chroot(path or safe_mkdtemp())
    self._pex_info = pex_info or PexInfo.default(self._interpreter)
    self._preamble = preamble or ''
    self._copy = copy

    self._shebang = self._interpreter.identity.hashbang()
    self._logger = logging.getLogger(__name__)
    self._frozen = False
    self._distributions = set()

  def _ensure_unfrozen(self, name='Operation'):
    if self._frozen:
      raise self.ImmutablePEX('%s is not allowed on a frozen PEX!' % name)

  @property
  def interpreter(self):
    return self._interpreter

  def chroot(self):
    return self._chroot

  def clone(self, into=None):
    """Clone this PEX environment into a new PEXBuilder.

    :keyword into: (optional) An optional destination directory to clone this PEXBuilder into.  If
      not specified, a temporary directory will be created.

    Clones PEXBuilder into a new location.  This is useful if the PEXBuilder has been frozen and
    rendered immutable.

    .. versionchanged:: 0.8
      The temporary directory created when ``into`` is not specified is now garbage collected on
      interpreter exit.
    """
    chroot_clone = self._chroot.clone(into=into)
    clone = self.__class__(
      chroot=chroot_clone,
      interpreter=self._interpreter,
      pex_info=self._pex_info.copy(),
      preamble=self._preamble,
      copy=self._copy)
    clone.set_shebang(self._shebang)
    clone._distributions = self._distributions.copy()
    return clone

  def path(self):
    return self.chroot().path()

  @property
  def info(self):
    return self._pex_info

  @info.setter
  def info(self, value):
    if not isinstance(value, PexInfo):
      raise TypeError('PEXBuilder.info must be a PexInfo!')
    self._ensure_unfrozen('Changing PexInfo')
    self._pex_info = value

  def add_source(self, filename, env_filename):
    """Add a source to the PEX environment.

    :param filename: The source filename to add to the PEX; None to create an empty file at
      `env_filename`.
    :param env_filename: The destination filename in the PEX.  This path
      must be a relative path.
    """
    self._ensure_unfrozen('Adding source')
    self._copy_or_link(filename, env_filename, "source")

  def add_resource(self, filename, env_filename):
    """Add a resource to the PEX environment.

    :param filename: The source filename to add to the PEX; None to create an empty file at
      `env_filename`.
    :param env_filename: The destination filename in the PEX.  This path
      must be a relative path.
    """
    self._ensure_unfrozen('Adding a resource')
    self._copy_or_link(filename, env_filename, "resource")

  def add_requirement(self, req):
    """Add a requirement to the PEX environment.

    :param req: A requirement that should be resolved in this environment.

    .. versionchanged:: 0.8
      Removed ``dynamic`` and ``repo`` keyword arguments as they were unused.
    """
    self._ensure_unfrozen('Adding a requirement')
    self._pex_info.add_requirement(req)

  def add_interpreter_constraint(self, ic):
    """Add an interpreter constraint to the PEX environment.

    :param ic: A version constraint on the interpreter used to build and run this PEX environment.

    """
    self._ensure_unfrozen('Adding an interpreter constraint')
    self._pex_info.add_interpreter_constraint(ic)

  def set_executable(self, filename, env_filename=None):
    """Set the executable for this environment.

    :param filename: The file that should be executed within the PEX environment when the PEX is
      invoked.
    :keyword env_filename: (optional) The name that the executable file should be stored as within
      the PEX.  By default this will be the base name of the given filename.

    The entry point of the PEX may also be specified via ``PEXBuilder.set_entry_point``.
    """
    self._ensure_unfrozen('Setting the executable')
    if self._pex_info.script:
      raise self.InvalidExecutableSpecification('Cannot set both entry point and script of PEX!')
    if env_filename is None:
      env_filename = os.path.basename(filename)
    if self._chroot.get("executable"):
      raise self.InvalidExecutableSpecification(
          "Setting executable on a PEXBuilder that already has one!")
    self._copy_or_link(filename, env_filename, "executable")
    entry_point = env_filename
    entry_point = entry_point.replace(os.path.sep, '.')
    self._pex_info.entry_point = entry_point.rpartition('.')[0]

  def set_script(self, script):
    """Set the entry point of this PEX environment based upon a distribution script.

    :param script: The script name as defined either by a console script or ordinary
      script within the setup.py of one of the distributions added to the PEX.
    :raises: :class:`PEXBuilder.InvalidExecutableSpecification` if the script is not found
      in any distribution added to the PEX.
    """

    # check if 'script' is a console_script
    dist, entry_point = get_entry_point_from_console_script(script, self._distributions)
    if entry_point:
      self.set_entry_point(entry_point)
      TRACER.log('Set entrypoint to console_script %r in %r' % (entry_point, dist))
      return

    # check if 'script' is an ordinary script
    dist, _, _ = get_script_from_distributions(script, self._distributions)
    if dist:
      if self._pex_info.entry_point:
        raise self.InvalidExecutableSpecification('Cannot set both entry point and script of PEX!')
      self._pex_info.script = script
      TRACER.log('Set entrypoint to script %r in %r' % (script, dist))
      return

    raise self.InvalidExecutableSpecification(
        'Could not find script %r in any distribution %s within PEX!' % (
            script, ', '.join(str(d) for d in self._distributions)))

  def set_entry_point(self, entry_point):
    """Set the entry point of this PEX environment.

    :param entry_point: The entry point of the PEX in the form of ``module`` or ``module:symbol``,
      or ``None``.
    :type entry_point: string or None

    By default the entry point is None.  The behavior of a ``None`` entry point is dropping into
    an interpreter.  If ``module``, it will be executed via ``runpy.run_module``.  If
    ``module:symbol``, it is equivalent to ``from module import symbol; symbol()``.

    The entry point may also be specified via ``PEXBuilder.set_executable``.
    """
    self._ensure_unfrozen('Setting an entry point')
    self._pex_info.entry_point = entry_point

  def set_shebang(self, shebang):
    """Set the exact shebang line for the PEX file.

    For example, pex_builder.set_shebang('/home/wickman/Local/bin/python3.4').  This is
    used to override the default behavior which is to have a #!/usr/bin/env line referencing an
    interpreter compatible with the one used to build the PEX.

    :param shebang: The shebang line. If it does not include the leading '#!' it will be added.
    :type shebang: str
    """
    self._shebang = '#!%s' % shebang if not shebang.startswith('#!') else shebang

  def _add_dist_dir(self, path, dist_name):
    for root, _, files in os.walk(path):
      for f in files:
        filename = os.path.join(root, f)
        relpath = os.path.relpath(filename, path)
        target = os.path.join(self._pex_info.internal_cache, dist_name, relpath)
        self._copy_or_link(filename, target)
    return CacheHelper.dir_hash(path)

  def _get_installer_paths(self, base):
    """Set up an overrides dict for WheelFile.install that installs the contents
    of a wheel into its own base in the pex dependencies cache.
    """
    return {
      'purelib': base,
      'headers': os.path.join(base, 'headers'),
      'scripts': os.path.join(base, 'bin'),
      'platlib': base,
      'data': base
    }

  def _add_dist_zip(self, path, dist_name):
    # We need to distinguish between wheels and other zips. Most of the time,
    # when we have a zip, it contains its contents in an importable form.
    # But wheels don't have to be importable, so we need to force them
    # into an importable shape. We can do that by installing it into its own
    # wheel dir.
    if dist_name.endswith("whl"):
      from pex.third_party.wheel.install import WheelFile
      tmp = safe_mkdtemp()
      whltmp = os.path.join(tmp, dist_name)
      os.mkdir(whltmp)
      wf = WheelFile(path)
      wf.install(overrides=self._get_installer_paths(whltmp), force=True)
      for root, _, files in os.walk(whltmp):
        pruned_dir = os.path.relpath(root, tmp)
        for f in files:
          fullpath = os.path.join(root, f)
          target = os.path.join(self._pex_info.internal_cache, pruned_dir, f)
          self._copy_or_link(fullpath, target)
      return CacheHelper.dir_hash(whltmp)

    with open_zip(path) as zf:
      for name in zf.namelist():
        if name.endswith('/'):
          continue
        target = os.path.join(self._pex_info.internal_cache, dist_name, name)
        self._chroot.write(zf.read(name), target)
      return CacheHelper.zip_hash(zf)

  def _prepare_code_hash(self):
    self._pex_info.code_hash = CacheHelper.pex_hash(self._chroot.path())

  def add_distribution(self, dist, dist_name=None):
    """Add a :class:`pkg_resources.Distribution` from its handle.

    :param dist: The distribution to add to this environment.
    :keyword dist_name: (optional) The name of the distribution e.g. 'Flask-0.10.0'.  By default
      this will be inferred from the distribution itself should it be formatted in a standard way.
    :type dist: :class:`pkg_resources.Distribution`
    """
    self._ensure_unfrozen('Adding a distribution')
    dist_name = dist_name or os.path.basename(dist.location)
    self._distributions.add(dist)

    if os.path.isdir(dist.location):
      dist_hash = self._add_dist_dir(dist.location, dist_name)
    else:
      dist_hash = self._add_dist_zip(dist.location, dist_name)

    # add dependency key so that it can rapidly be retrieved from cache
    self._pex_info.add_distribution(dist_name, dist_hash)

  def add_dist_location(self, dist, name=None):
    """Add a distribution by its location on disk.

    :param dist: The path to the distribution to add.
    :keyword name: (optional) The name of the distribution, should the dist directory alone be
      ambiguous.  Packages contained within site-packages directories may require specifying
      ``name``.
    :raises PEXBuilder.InvalidDistribution: When the path does not contain a matching distribution.

    PEX supports packed and unpacked .whl and .egg distributions, as well as any distribution
    supported by setuptools/pkg_resources.
    """
    self._ensure_unfrozen('Adding a distribution')
    bdist = DistributionHelper.distribution_from_path(dist)
    if bdist is None:
      raise self.InvalidDistribution('Could not find distribution at %s' % dist)
    self.add_distribution(bdist)
    self.add_requirement(bdist.as_requirement())

  def add_egg(self, egg):
    """Alias for add_dist_location."""
    self._ensure_unfrozen('Adding an egg')
    return self.add_dist_location(egg)

  def _precompile_source(self):
    source_relpaths = [path for label in ('source', 'executable', 'main', 'bootstrap')
                       for path in self._chroot.filesets.get(label, ()) if path.endswith('.py')]

    compiler = Compiler(self.interpreter)
    compiled_relpaths = compiler.compile(self._chroot.path(), source_relpaths)
    for compiled in compiled_relpaths:
      self._chroot.touch(compiled, label='bytecode')

  def _prepare_manifest(self):
    self._chroot.write(self._pex_info.dump(sort_keys=True).encode('utf-8'),
                       PexInfo.PATH, label='manifest')

  def _prepare_main(self):
    self._chroot.write(to_bytes(self._preamble + '\n' + BOOTSTRAP_ENVIRONMENT),
        '__main__.py', label='main')

  def _copy_or_link(self, src, dst, label=None):
    if src is None:
      self._chroot.touch(dst, label)
    elif self._copy:
      self._chroot.copy(src, dst, label)
    else:
      self._chroot.link(src, dst, label)

  def _prepare_bootstrap(self):
    from . import vendor
    vendor.vendor_runtime(chroot=self._chroot,
                          dest_basedir=BOOTSTRAP_DIR,
                          label='bootstrap',
                          # NB: We use wheel here in the builder, but that's only at build-time.
                          root_module_names=['pkg_resources'])

    source_name = 'pex'
    provider = get_provider(source_name)
    if not isinstance(provider, DefaultProvider):
      mod = __import__(source_name, fromlist=['ignore'])
      provider = ZipProvider(mod)
    for package in ('', 'third_party'):
      for fn in provider.resource_listdir(package):
        if fn.endswith('.py'):
          rel_path = os.path.join(package, fn)
          self._chroot.write(provider.get_resource_string(source_name, rel_path),
                             os.path.join(BOOTSTRAP_DIR, source_name, rel_path), 'bootstrap')

    # Setup a re-director package to support the legacy pex runtime `_pex` APIs through a
    # VendorImporter.
    self._chroot.touch(os.path.join(BOOTSTRAP_DIR, LEGACY_BOOSTRAP_PKG, '__init__.py'), 'bootstrap')

  def freeze(self, bytecode_compile=True):
    """Freeze the PEX.

    :param bytecode_compile: If True, precompile .py files into .pyc files when freezing code.

    Freezing the PEX writes all the necessary metadata and environment bootstrapping code.  It may
    only be called once and renders the PEXBuilder immutable.
    """
    self._ensure_unfrozen('Freezing the environment')
    self._prepare_code_hash()
    self._prepare_manifest()
    self._prepare_bootstrap()
    self._prepare_main()
    if bytecode_compile:
      self._precompile_source()
    self._frozen = True

  def build(self, filename, bytecode_compile=True, deterministic_timestamp=False):
    """Package the PEX into a zipfile.

    :param filename: The filename where the PEX should be stored.
    :param bytecode_compile: If True, precompile .py files into .pyc files.
    :param deterministic_timestamp: If True, will use our hardcoded time for zipfile timestamps.

    If the PEXBuilder is not yet frozen, it will be frozen by ``build``.  This renders the
    PEXBuilder immutable.
    """
    if not self._frozen:
      self.freeze(bytecode_compile=bytecode_compile)
    try:
      os.unlink(filename + '~')
      self._logger.warn('Previous binary unexpectedly exists, cleaning: %s' % (filename + '~'))
    except OSError:
      # The expectation is that the file does not exist, so continue
      pass
    if os.path.dirname(filename):
      safe_mkdir(os.path.dirname(filename))
    with open(filename + '~', 'ab') as pexfile:
      assert os.path.getsize(pexfile.name) == 0
      pexfile.write(to_bytes('%s\n' % self._shebang))
    self._chroot.zip(filename + '~', mode='a', deterministic_timestamp=deterministic_timestamp)
    if os.path.exists(filename):
      os.unlink(filename)
    os.rename(filename + '~', filename)
    chmod_plus_x(filename)
