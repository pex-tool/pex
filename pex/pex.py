# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import sys
from distutils import sysconfig
from site import USER_SITE

import pex.third_party.pkg_resources as pkg_resources
from pex import third_party
from pex.bootstrap import Bootstrap
from pex.common import die
from pex.environment import PEXEnvironment
from pex.executor import Executor
from pex.finders import (
    get_entry_point_from_console_script,
    get_script_from_distributions,
    unregister_finders
)
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.third_party.pkg_resources import EntryPoint, WorkingSet, find_distributions
from pex.tracer import TRACER
from pex.util import iter_pth_paths, merge_split, named_temporary_file
from pex.variables import ENV


class DevNull(object):
  def __init__(self):
    pass

  def write(self, *args, **kw):
    pass

  def flush(self):
    pass


class PEX(object):  # noqa: T000
  """PEX, n. A self-contained python environment."""

  class Error(Exception): pass
  class NotFound(Error): pass
  class InvalidEntryPoint(Error): pass

  @classmethod
  def clean_environment(cls):
    try:
      del os.environ['MACOSX_DEPLOYMENT_TARGET']
    except KeyError:
      pass
    # Cannot change dictionary size during __iter__
    filter_keys = [key for key in os.environ if key.startswith('PEX_')]
    for key in filter_keys:
      del os.environ[key]

  def __init__(self, pex=sys.argv[0], interpreter=None, env=ENV, verify_entry_point=False):
    self._pex = pex
    self._interpreter = interpreter or PythonInterpreter.get()
    self._pex_info = PexInfo.from_pex(self._pex)
    self._pex_info_overrides = PexInfo.from_env(env=env)
    self._vars = env
    self._envs = []
    self._working_set = None
    if verify_entry_point:
      self._do_entry_point_verification()

  def _activate(self):
    if not self._working_set:
      working_set = WorkingSet([])

      # set up the local .pex environment
      pex_info = self._pex_info.copy()
      pex_info.update(self._pex_info_overrides)
      pex_info.merge_pex_path(self._vars.PEX_PATH)
      self._envs.append(PEXEnvironment(self._pex, pex_info, interpreter=self._interpreter))
      # N.B. by this point, `pex_info.pex_path` will contain a single pex path
      # merged from pex_path in `PEX-INFO` and `PEX_PATH` set in the environment.
      # `PEX_PATH` entries written into `PEX-INFO` take precedence over those set
      # in the environment.
      if pex_info.pex_path:
        # set up other environments as specified in pex_path
        for pex_path in filter(None, pex_info.pex_path.split(os.pathsep)):
          pex_info = PexInfo.from_pex(pex_path)
          pex_info.update(self._pex_info_overrides)
          self._envs.append(PEXEnvironment(pex_path, pex_info, interpreter=self._interpreter))

      # activate all of them
      for env in self._envs:
        for dist in env.activate():
          working_set.add(dist)

      self._working_set = working_set

    return self._working_set

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

    # Handle .pth injected paths as extras.
    sitedirs = cls._get_site_packages()
    for pth_path in cls._scan_pth_files(sitedirs):
      TRACER.log('Found .pth file: %s' % pth_path, V=3)
      for extras_path in iter_pth_paths(pth_path):
        yield extras_path

  @staticmethod
  def _scan_pth_files(dir_paths):
    """Given an iterable of directory paths, yield paths to all .pth files within."""
    for dir_path in dir_paths:
      if not os.path.exists(dir_path):
        continue

      pth_filenames = (f for f in os.listdir(dir_path) if f.endswith('.pth'))
      for pth_filename in pth_filenames:
        yield os.path.join(dir_path, pth_filename)

  @staticmethod
  def _get_site_packages():
    try:
      from site import getsitepackages
      return set(getsitepackages())
    except ImportError:
      return set()

  @classmethod
  def site_libs(cls):
    site_libs = cls._get_site_packages()
    site_libs.update([sysconfig.get_python_lib(plat_specific=False),
                      sysconfig.get_python_lib(plat_specific=True)])
    # On windows getsitepackages() returns the python stdlib too.
    if sys.prefix in site_libs:
      site_libs.remove(sys.prefix)
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

    NOTE: This method mutates modules' __path__ attributes in sys.modules, so this is currently an
    irreversible operation.
    """

    modules = modules or sys.modules
    new_modules = {}

    for module_name, module in modules.items():
      # builtins can stay
      if not hasattr(module, '__path__'):
        new_modules[module_name] = module
        continue

      # Unexpected objects, e.g. PEP 420 namespace packages, should just be dropped.
      if not isinstance(module.__path__, list):
        TRACER.log('Dropping %s' % (module_name,), V=3)
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
  def minimum_sys_path(cls, site_libs, inherit_path):
    scrub_paths = OrderedSet()
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
        TRACER.log('Not a tainted path element: %s' % path_element, V=2)

    user_site_distributions.update(all_distribution_paths(USER_SITE))

    if inherit_path == 'false':
      scrub_paths = site_distributions | user_site_distributions
      for path in user_site_distributions:
        TRACER.log('Scrubbing from user site: %s' % path)
      for path in site_distributions:
        TRACER.log('Scrubbing from site-packages: %s' % path)

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
  def minimum_sys(cls, inherit_path):
    """Return the minimum sys necessary to run this interpreter, a la python -S.

    :returns: (sys.path, sys.path_importer_cache, sys.modules) tuple of a
      bare python installation.
    """
    site_libs = set(cls.site_libs())
    for site_lib in site_libs:
      TRACER.log('Found site-library: %s' % site_lib)
    for extras_path in cls._extras_paths():
      TRACER.log('Found site extra: %s' % extras_path)
      site_libs.add(extras_path)
    site_libs = set(os.path.normpath(path) for path in site_libs)

    sys_path, sys_path_importer_cache = cls.minimum_sys_path(site_libs, inherit_path)
    sys_modules = cls.minimum_sys_modules(site_libs)

    return sys_path, sys_path_importer_cache, sys_modules

  @classmethod
  def patch_pkg_resources(cls, working_set):
    """Patch pkg_resources given a new working set."""
    pkg_resources.working_set = working_set
    pkg_resources.require = working_set.require
    pkg_resources.iter_entry_points = working_set.iter_entry_points
    pkg_resources.run_script = pkg_resources.run_main = working_set.run_script
    pkg_resources.add_activation_listener = working_set.subscribe

  # Thar be dragons -- when this function exits, the interpreter is potentially in a wonky state
  # since the patches here (minimum_sys_modules for example) actually mutate global state.
  def patch_sys(self, inherit_path):
    """Patch sys with all site scrubbed."""
    def patch_dict(old_value, new_value):
      old_value.clear()
      old_value.update(new_value)

    def patch_all(path, path_importer_cache, modules):
      sys.path[:] = path
      patch_dict(sys.path_importer_cache, path_importer_cache)
      patch_dict(sys.modules, modules)

    new_sys_path, new_sys_path_importer_cache, new_sys_modules = self.minimum_sys(inherit_path)

    new_sys_path.extend(merge_split(self._pex_info.pex_path, self._vars.PEX_PATH))

    patch_all(new_sys_path, new_sys_path_importer_cache, new_sys_modules)

  def _wrap_coverage(self, runner, *args):
    if not self._vars.PEX_COVERAGE and self._vars.PEX_COVERAGE_FILENAME is None:
      return runner(*args)

    try:
      import coverage
    except ImportError:
      die('Could not bootstrap coverage module, aborting.')

    pex_coverage_filename = self._vars.PEX_COVERAGE_FILENAME
    if pex_coverage_filename is not None:
      cov = coverage.coverage(data_file=pex_coverage_filename)
    else:
      cov = coverage.coverage(data_suffix=True)

    TRACER.log('Starting coverage.')
    cov.start()

    try:
      return runner(*args)
    finally:
      TRACER.log('Stopping coverage')
      cov.stop()

      # TODO(wickman) Post-process coverage to elide $PEX_ROOT and make
      # the report more useful/less noisy.  #89
      if pex_coverage_filename:
        cov.save()
      else:
        cov.report(show_missing=False, ignore_errors=True, file=sys.stdout)

  def _wrap_profiling(self, runner, *args):
    if not self._vars.PEX_PROFILE and self._vars.PEX_PROFILE_FILENAME is None:
      return runner(*args)

    pex_profile_filename = self._vars.PEX_PROFILE_FILENAME
    pex_profile_sort = self._vars.PEX_PROFILE_SORT
    try:
      import cProfile as profile
    except ImportError:
      import profile

    profiler = profile.Profile()

    try:
      return profiler.runcall(runner, *args)
    finally:
      if pex_profile_filename is not None:
        profiler.dump_stats(pex_profile_filename)
      else:
        profiler.print_stats(sort=pex_profile_sort)

  def path(self):
    """Return the path this PEX was built at."""
    return self._pex

  def execute(self):
    """Execute the PEX.

    This function makes assumptions that it is the last function called by
    the interpreter.
    """
    teardown_verbosity = self._vars.PEX_TEARDOWN_VERBOSE
    try:
      pex_inherit_path = self._vars.PEX_INHERIT_PATH
      if pex_inherit_path == "false":
        pex_inherit_path = self._pex_info.inherit_path
      self.patch_sys(pex_inherit_path)
      working_set = self._activate()
      self.patch_pkg_resources(working_set)
      exit_code = self._wrap_coverage(self._wrap_profiling, self._execute)
      if exit_code:
        sys.exit(exit_code)
    except Exception:
      # Allow the current sys.excepthook to handle this app exception before we tear things down in
      # finally, then reraise so that the exit status is reflected correctly.
      sys.excepthook(*sys.exc_info())
      raise
    except SystemExit as se:
      # Print a SystemExit error message, avoiding a traceback in python3.
      # This must happen here, as sys.stderr is about to be torn down
      if not isinstance(se.code, int) and se.code is not None:
        print(se.code, file=sys.stderr)
      raise
    finally:
      # squash all exceptions on interpreter teardown -- the primary type here are
      # atexit handlers failing to run because of things such as:
      #   http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
      if not teardown_verbosity:
        sys.stderr.flush()
        sys.stderr = DevNull()
        sys.excepthook = lambda *a, **kw: None

  def _execute(self):
    force_interpreter = self._vars.PEX_INTERPRETER

    self.clean_environment()

    if force_interpreter:
      TRACER.log('PEX_INTERPRETER specified, dropping into interpreter')
      return self.execute_interpreter()

    if self._pex_info_overrides.script and self._pex_info_overrides.entry_point:
      die('Cannot specify both script and entry_point for a PEX!')

    if self._pex_info.script and self._pex_info.entry_point:
      die('Cannot specify both script and entry_point for a PEX!')

    if self._pex_info_overrides.script:
      return self.execute_script(self._pex_info_overrides.script)
    elif self._pex_info_overrides.entry_point:
      return self.execute_entry(self._pex_info_overrides.entry_point)
    elif self._pex_info.script:
      return self.execute_script(self._pex_info.script)
    elif self._pex_info.entry_point:
      return self.execute_entry(self._pex_info.entry_point)
    else:
      TRACER.log('No entry point specified, dropping into interpreter')
      return self.execute_interpreter()

  @classmethod
  def demote_bootstrap(cls):
    TRACER.log('Bootstrap complete, performing final sys.path modifications...')

    should_log = {level: TRACER.should_log(V=level) for level in range(1, 10)}

    def log(msg, V=1):
      if should_log.get(V, False):
        print('pex: {}'.format(msg), file=sys.stderr)

    # Remove the third party resources pex uses and demote pex bootstrap code to the end of
    # sys.path for the duration of the run to allow conflicting versions supplied by user
    # dependencies to win during the course of the execution of user code.
    unregister_finders()
    third_party.uninstall()

    bootstrap = Bootstrap.locate()
    log('Demoting code from %s' % bootstrap, V=2)
    for module in bootstrap.demote():
      log('un-imported {}'.format(module), V=9)

    import pex
    log('Re-imported pex from {}'.format(pex.__path__), V=3)

    log('PYTHONPATH contains:')
    for element in sys.path:
      log('  %c %s' % (' ' if os.path.exists(element) else '*', element))
    log('  * - paths that do not exist or will be imported via zipimport')

  def execute_interpreter(self):
    args = sys.argv[1:]
    if args:
      # NB: We take care here to setup sys.argv to match how CPython does it for each case.
      arg = args[0]
      if arg == '-c':
        content = args[1]
        sys.argv = ['-c'] + args[2:]
        self.execute_content('-c <cmd>', content, argv0='-c')
      elif arg == '-m':
        module = args[1]
        sys.argv = args[1:]
        self.execute_module(module)
      else:
        try:
          if arg == '-':
            content = sys.stdin.read()
          else:
            with open(arg) as fp:
              content = fp.read()
        except IOError as e:
          die("Could not open %s in the environment [%s]: %s" % (arg, sys.argv[0], e))
        sys.argv = args
        self.execute_content(arg, content)
    else:
      self.demote_bootstrap()

      import code
      code.interact()

  def execute_script(self, script_name):
    dists = list(self._activate())

    dist, entry_point = get_entry_point_from_console_script(script_name, dists)
    if entry_point:
      TRACER.log('Found console_script %r in %r' % (entry_point, dist))
      sys.exit(self.execute_entry(entry_point))

    dist, script_path, script_content = get_script_from_distributions(script_name, dists)
    if not dist:
      raise self.NotFound('Could not find script %r in pex!' % script_name)
    TRACER.log('Found script %r in %r' % (script_name, dist))
    return self.execute_content(script_path, script_content, argv0=script_name)

  @classmethod
  def execute_content(cls, name, content, argv0=None):
    argv0 = argv0 or name
    try:
      ast = compile(content, name, 'exec', flags=0, dont_inherit=1)
    except SyntaxError:
      die('Unable to parse %s. PEX script support only supports Python scripts.' % name)

    cls.demote_bootstrap()

    from pex.compatibility import exec_function
    sys.argv[0] = argv0
    globals_map = globals()
    globals_map['__name__'] = '__main__'
    globals_map['__file__'] = name
    exec_function(ast, globals_map)

  @classmethod
  def execute_entry(cls, entry_point):
    runner = cls.execute_pkg_resources if ':' in entry_point else cls.execute_module
    return runner(entry_point)

  @classmethod
  def execute_module(cls, module_name):
    cls.demote_bootstrap()

    import runpy
    runpy.run_module(module_name, run_name='__main__')

  @classmethod
  def execute_pkg_resources(cls, spec):
    entry = EntryPoint.parse("run = {}".format(spec))
    cls.demote_bootstrap()

    runner = entry.resolve()
    return runner()

  def cmdline(self, args=()):
    """The commandline to run this environment.

    :keyword args: Additional arguments to be passed to the application being invoked by the
      environment.
    """
    cmds = [self._interpreter.binary]
    cmds.append(self._pex)
    cmds.extend(args)
    return cmds

  def run(self, args=(), with_chroot=False, blocking=True, setsid=False, **kwargs):
    """Run the PythonEnvironment in an interpreter in a subprocess.

    :keyword args: Additional arguments to be passed to the application being invoked by the
      environment.
    :keyword with_chroot: Run with cwd set to the environment's working directory.
    :keyword blocking: If true, return the return code of the subprocess.
      If false, return the Popen object of the invoked subprocess.
    :keyword setsid: If true, run the PEX in a separate operating system session.

    Remaining keyword arguments are passed directly to subprocess.Popen.
    """
    self.clean_environment()

    cmdline = self.cmdline(args)
    TRACER.log('PEX.run invoking %s' % ' '.join(cmdline))
    process = Executor.open_process(cmdline,
                                    cwd=self._pex if with_chroot else os.getcwd(),
                                    preexec_fn=os.setsid if setsid else None,
                                    stdin=kwargs.pop('stdin', None),
                                    stdout=kwargs.pop('stdout', None),
                                    stderr=kwargs.pop('stderr', None),
                                    **kwargs)
    return process.wait() if blocking else process

  def _do_entry_point_verification(self):

    entry_point = self._pex_info.entry_point
    ep_split = entry_point.split(':')

    # a.b.c:m ->
    # ep_module = 'a.b.c'
    # ep_method = 'm'

    # Only module is specified
    if len(ep_split) == 1:
      ep_module = ep_split[0]
      import_statement = 'import {}'.format(ep_module)
    elif len(ep_split) == 2:
      ep_module = ep_split[0]
      ep_method = ep_split[1]
      import_statement = 'from {} import {}'.format(ep_module, ep_method)
    else:
      raise self.InvalidEntryPoint("Failed to parse: `{}`".format(entry_point))

    with named_temporary_file() as fp:
      fp.write(import_statement.encode('utf-8'))
      fp.close()
      retcode = self.run([fp.name], env={'PEX_INTERPRETER': '1'})
      if retcode != 0:
        raise self.InvalidEntryPoint('Invalid entry point: `{}`\n'
                                     'Entry point verification failed: `{}`'
                                     .format(entry_point, import_statement))
