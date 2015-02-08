# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import subprocess
import sys
from contextlib import contextmanager
from distutils import sysconfig
from site import USER_SITE

import pkg_resources
from pkg_resources import EntryPoint, find_distributions

from .common import safe_mkdir
from .compatibility import exec_function
from .environment import PEXEnvironment
from .interpreter import PythonInterpreter
from .orderedset import OrderedSet
from .pex_info import PexInfo
from .tracer import TraceLogger

TRACER = TraceLogger(predicate=TraceLogger.env_filter('PEX_VERBOSE'), prefix='pex: ')


class DevNull(object):
  def __init__(self):
    pass

  def write(self, *args, **kw):
    pass


class PEX(object):  # noqa: T000
  """PEX, n. A self-contained python environment."""

  class Error(Exception): pass
  class NotFound(Error): pass

  @classmethod
  def start_coverage(cls):
    try:
      import coverage
      cov = coverage.coverage(auto_data=True, data_suffix=True)
      cov.start()
    except ImportError:
      sys.stderr.write('Could not bootstrap coverage module!\n')

  @classmethod
  def clean_environment(cls, forking=False):
    try:
      del os.environ['MACOSX_DEPLOYMENT_TARGET']
    except KeyError:
      pass
    if not forking:
      for key in filter(lambda key: key.startswith('PEX_'), os.environ):
        del os.environ[key]

  def __init__(self, pex=sys.argv[0], interpreter=None):
    self._pex = pex
    self._pex_info = PexInfo.from_pex(self._pex)
    self._env = PEXEnvironment(self._pex, self._pex_info)
    self._interpreter = interpreter or PythonInterpreter.get()

  @property
  def info(self):
    return self._pex_info

  def entry(self):
    """Return the module spec of the entry point of this PEX.

      :returns: The entry point for this environment as a string, otherwise
        ``None`` if there is no specific entry point.
    """
    if 'PEX_MODULE' in os.environ:
      TRACER.log('PEX_MODULE override detected: %s' % os.environ['PEX_MODULE'])
      return os.environ['PEX_MODULE']
    entry_point = self._pex_info.entry_point
    if entry_point:
      TRACER.log('Using prescribed entry point: %s' % entry_point)
      return str(entry_point)

  @classmethod
  def _extras_paths(cls):
    standard_lib = sysconfig.get_python_lib(standard_lib=True)
    try:
      makefile = sysconfig.parse_makefile(sysconfig.get_makefile_filename())
    except (AttributeError, IOError):
      # This is not available by default in PyPy's distutils.sysconfig or it simply is
      # no longer available on the system (IOError ENOENT)
      makefile = {}
    extras_paths = filter(None, makefile.get('EXTRASPATH', '').split(':'))
    for path in extras_paths:
      yield os.path.join(standard_lib, path)

  @classmethod
  def _site_libs(cls):
    try:
      from site import getsitepackages
      site_libs = set(getsitepackages())
    except ImportError:
      site_libs = set()
    site_libs.update([sysconfig.get_python_lib(plat_specific=False),
                      sysconfig.get_python_lib(plat_specific=True)])
    real_site_libs = set(os.path.realpath(path) for path in site_libs)
    return site_libs | real_site_libs

  @classmethod
  def _tainted_path(cls, path, site_libs):
    paths = frozenset([path, os.path.realpath(path)])
    return any(path.startswith(site_lib) for site_lib in site_libs for path in paths)

  @classmethod
  def minimum_sys_modules(cls, site_libs, modules=None):
    """Given a set of site-packages paths, return a "clean" sys.modules.

    When importing site, modules within sys.modules have their __path__'s populated with
    additional paths as defined by *-nspkg.pth in site-packages, or alternately by distribution
    metadata such as *.dist-info/namespace_packages.txt.  This can possibly cause namespace
    packages to leak into imports despite being scrubbed from sys.path.

    NOTE: This method mutates modules' __path__ attributes in sys.module, so this is currently an
    irreversible operation.
    """

    modules = modules or sys.modules
    new_modules = {}

    for module_name, module in modules.items():
      # builtins can stay
      if not hasattr(module, '__path__'):
        new_modules[module_name] = module
        continue

      # Pop off site-impacting __path__ elements in-place.
      for k in reversed(range(len(module.__path__))):
        if cls._tainted_path(module.__path__[k], site_libs):
          TRACER.log('Scrubbing %s.__path__: %s' % (module_name, module.__path__[k]), V=3)
          module.__path__.pop(k)

      # It still contains path elements not in site packages, so it can stay in sys.modules
      if module.__path__:
        new_modules[module_name] = module

    return new_modules

  @classmethod
  def minimum_sys_path(cls, site_libs):
    site_distributions = OrderedSet()
    user_site_distributions = OrderedSet()

    def all_distribution_paths(path):
      locations = set(dist.location for dist in find_distributions(path))
      return set([path]) | locations | set(os.path.realpath(path) for path in locations)

    for path_element in sys.path:
      if cls._tainted_path(path_element, site_libs):
        TRACER.log('Tainted path element: %s' % path_element)
        site_distributions.update(all_distribution_paths(path_element))
      else:
        TRACER.log('Not a tained path element: %s' % path_element, V=2)

    user_site_distributions.update(all_distribution_paths(USER_SITE))

    for path in site_distributions:
      TRACER.log('Scrubbing from site-packages: %s' % path)

    for path in user_site_distributions:
      TRACER.log('Scrubbing from user site: %s' % path)

    scrub_paths = site_distributions | user_site_distributions
    scrubbed_sys_path = list(OrderedSet(sys.path) - scrub_paths)
    scrub_from_importer_cache = filter(
      lambda key: any(key.startswith(path) for path in scrub_paths),
      sys.path_importer_cache.keys())
    scrubbed_importer_cache = dict((key, value) for (key, value) in sys.path_importer_cache.items()
      if key not in scrub_from_importer_cache)

    for importer_cache_entry in scrub_from_importer_cache:
      TRACER.log('Scrubbing from path_importer_cache: %s' % importer_cache_entry, V=2)

    return scrubbed_sys_path, scrubbed_importer_cache

  @classmethod
  def minimum_sys(cls):
    """Return the minimum sys necessary to run this interpreter, a la python -S.

    :returns: (sys.path, sys.path_importer_cache, sys.modules) tuple of a
      bare python installation.
    """
    site_libs = set(cls._site_libs())
    for site_lib in site_libs:
      TRACER.log('Found site-library: %s' % site_lib)
    for extras_path in cls._extras_paths():
      TRACER.log('Found site extra: %s' % extras_path)
      site_libs.add(extras_path)
    site_libs = set(os.path.normpath(path) for path in site_libs)

    sys_path, sys_path_importer_cache = cls.minimum_sys_path(site_libs)
    sys_modules = cls.minimum_sys_modules(site_libs)

    return sys_path, sys_path_importer_cache, sys_modules

  @classmethod
  @contextmanager
  def patch_pkg_resources(cls, working_set):
    """Patch pkg_resources given a new working set."""
    def patch(working_set):
      pkg_resources.working_set = working_set
      pkg_resources.require = working_set.require
      pkg_resources.iter_entry_points = working_set.iter_entry_points
      pkg_resources.run_script = pkg_resources.run_main = working_set.run_script
      pkg_resources.add_activation_listener = working_set.subscribe

    old_working_set = pkg_resources.working_set
    patch(working_set)
    try:
      yield
    finally:
      patch(old_working_set)

  # Thar be dragons -- when this contextmanager exits, the interpreter is
  # potentially in a wonky state since the patches here (minimum_sys_modules
  # for example) actually mutate global state.  This should not be
  # considered a reversible operation despite being a contextmanager.
  @classmethod
  @contextmanager
  def patch_sys(cls):
    """Patch sys with all site scrubbed."""
    def patch_dict(old_value, new_value):
      old_value.clear()
      old_value.update(new_value)

    def patch_all(path, path_importer_cache, modules):
      sys.path[:] = path
      patch_dict(sys.path_importer_cache, path_importer_cache)
      patch_dict(sys.modules, modules)

    old_sys_path, old_sys_path_importer_cache, old_sys_modules = (
        sys.path[:], sys.path_importer_cache.copy(), sys.modules.copy())
    new_sys_path, new_sys_path_importer_cache, new_sys_modules = cls.minimum_sys()

    patch_all(new_sys_path, new_sys_path_importer_cache, new_sys_modules)

    try:
      yield
    finally:
      patch_all(old_sys_path, old_sys_path_importer_cache, old_sys_modules)

  def execute(self, args=()):
    """Execute the PEX.

    This function makes assumptions that it is the last function called by
    the interpreter.
    """

    entry_point = self.entry()

    try:
      with self.patch_sys():
        working_set = self._env.activate()
        if 'PEX_COVERAGE' in os.environ:
          self.start_coverage()
        TRACER.log('PYTHONPATH contains:')
        for element in sys.path:
          TRACER.log('  %c %s' % (' ' if os.path.exists(element) else '*', element))
        TRACER.log('  * - paths that do not exist or will be imported via zipimport')
        with self.patch_pkg_resources(working_set):
          if entry_point and 'PEX_INTERPRETER' not in os.environ:
            self.execute_entry(entry_point, args)
          else:
            self.execute_interpreter()
    except Exception:
      # Allow the current sys.excepthook to handle this app exception before we tear things down in
      # finally, then reraise so that the exit status is reflected correctly.
      sys.excepthook(*sys.exc_info())
      raise
    finally:
      # squash all exceptions on interpreter teardown -- the primary type here are
      # atexit handlers failing to run because of things such as:
      #   http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
      if 'PEX_TEARDOWN_VERBOSE' not in os.environ:
        sys.stderr.flush()
        sys.stderr = DevNull()
        sys.excepthook = lambda *a, **kw: None

  @classmethod
  def execute_interpreter(cls):
    force_interpreter = 'PEX_INTERPRETER' in os.environ
    if force_interpreter:
      del os.environ['PEX_INTERPRETER']
    TRACER.log('%s, dropping into interpreter' % (
        'PEX_INTERPRETER specified' if force_interpreter else 'No entry point specified'))
    if sys.argv[1:]:
      try:
        with open(sys.argv[1]) as fp:
          ast = compile(fp.read(), fp.name, 'exec', flags=0, dont_inherit=1)
      except IOError as e:
        print("Could not open %s in the environment [%s]: %s" % (sys.argv[1], sys.argv[0], e))
        sys.exit(1)
      sys.argv = sys.argv[1:]
      old_name = globals()['__name__']
      try:
        globals()['__name__'] = '__main__'
        exec_function(ast, globals())
      finally:
        globals()['__name__'] = old_name
    else:
      import code
      code.interact()

  @classmethod
  def execute_entry(cls, entry_point, args=None):
    if args:
      sys.argv = args
    runner = cls.execute_pkg_resources if ":" in entry_point else cls.execute_module

    if 'PEX_PROFILE' not in os.environ:
      runner(entry_point)
    else:
      import pstats, cProfile
      profile_output = os.environ['PEX_PROFILE']
      safe_mkdir(os.path.dirname(profile_output))
      cProfile.runctx('runner(entry_point)', globals=globals(), locals=locals(),
                      filename=profile_output)
      try:
        entries = int(os.environ.get('PEX_PROFILE_ENTRIES', 1000))
      except ValueError:
        entries = 1000
      pstats.Stats(profile_output).sort_stats(
          os.environ.get('PEX_PROFILE_SORT', 'cumulative')).print_stats(entries)

  @staticmethod
  def execute_module(module_name):
    import runpy
    runpy.run_module(module_name, run_name='__main__')

  @staticmethod
  def execute_pkg_resources(spec):
    entry = EntryPoint.parse("run = {0}".format(spec))
    runner = entry.load(require=False)  # trust that the environment is sane
    runner()

  def cmdline(self, args=()):
    """The commandline to run this environment.

    :keyword args: Additional arguments to be passed to the application being invoked by the
      environment.
    """
    cmds = [self._interpreter.binary]
    cmds.append(self._pex)
    cmds.extend(args)
    return cmds

  def run(self, args=(), with_chroot=False, blocking=True, setsid=False, **kw):
    """Run the PythonEnvironment in an interpreter in a subprocess.

    :keyword args: Additional arguments to be passed to the application being invoked by the
      environment.
    :keyword with_chroot: Run with cwd set to the environment's working directory.
    :keyword blocking: If true, return the return code of the subprocess.
      If false, return the Popen object of the invoked subprocess.
    :keyword setsid: If true, run the PEX in a separate operating system session.

    Remaining keyword arguments are passed directly to subprocess.Popen.
    """
    self.clean_environment(forking=True)

    cmdline = self.cmdline(args)
    TRACER.log('PEX.run invoking %s' % ' '.join(cmdline))
    process = subprocess.Popen(cmdline, cwd=self._pex if with_chroot else os.getcwd(),
                               preexec_fn=os.setsid if setsid else None, **kw)
    return process.wait() if blocking else process
