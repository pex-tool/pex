from __future__ import absolute_import, print_function

from distutils import sysconfig
import os
from site import USER_SITE
import sys


from .common import mutable_sys, safe_mkdir
from .compatibility import exec_function
from .environment import PEXEnvironment
from .interpreter import PythonInterpreter
from .orderedset import OrderedSet
from .pex_info import PexInfo
from .tracer import Tracer

from pkg_resources import EntryPoint, find_distributions


TRACER = Tracer(predicate=Tracer.env_filter('PEX_VERBOSE'), prefix='twitter.common.python.pex: ')


class PEX(object):
  """
    PEX, n. A self-contained python environment.
  """
  class Error(Exception): pass
  class NotFound(Error): pass

  @staticmethod
  def start_coverage():
    try:
      import coverage
      cov = coverage.coverage(auto_data=True, data_suffix=True,
        data_file='.coverage.%s' % os.environ['PEX_COVERAGE'])
      cov.start()
    except ImportError:
      sys.stderr.write('Could not bootstrap coverage module!\n')

  @classmethod
  def clean_environment(cls, forking=False):
    os.unsetenv('MACOSX_DEPLOYMENT_TARGET')
    if not forking:
      for key in filter(lambda key: key.startswith('PEX_'), os.environ):
        os.unsetenv(key)

  def __init__(self, pex=sys.argv[0], interpreter=None):
    self._pex = pex
    self._pex_info = PexInfo.from_pex(self._pex)
    self._env = PEXEnvironment(self._pex, self._pex_info)
    self._interpreter = interpreter or PythonInterpreter.get()

  @property
  def info(self):
    return self._pex_info

  def entry(self):
    """
      Return the module spec of the entry point of this PEX.  None if there
      is no entry point for this environment.
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
    return set([sysconfig.get_python_lib(plat_specific=False),
                sysconfig.get_python_lib(plat_specific=True)])

  @classmethod
  def minimum_path(cls):
    """
      Return as a tuple the emulated sys.path and sys.path_importer_cache of
      a bare python installation, a la python -S.
    """
    site_libs = set(cls._site_libs())
    for site_lib in site_libs:
      TRACER.log('Found site-library: %s' % site_lib)
    for extras_path in cls._extras_paths():
      TRACER.log('Found site extra: %s' % extras_path)
      site_libs.add(extras_path)
    site_libs = set(os.path.normpath(path) for path in site_libs)

    site_distributions = OrderedSet()
    for path_element in sys.path:
      if any(path_element.startswith(site_lib) for site_lib in site_libs):
        TRACER.log('Inspecting path element: %s' % path_element, V=2)
        site_distributions.update(dist.location for dist in find_distributions(path_element))

    user_site_distributions = OrderedSet(dist.location for dist in find_distributions(USER_SITE))

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
    return scrubbed_sys_path, scrubbed_importer_cache

  def execute(self, args=()):
    entry_point = self.entry()
    with mutable_sys():
      sys.path, sys.path_importer_cache = self.minimum_path()
      self._env.activate()
      if 'PEX_COVERAGE' in os.environ:
        PEX.start_coverage()
      TRACER.log('PYTHONPATH contains:')
      for element in sys.path:
        TRACER.log('  %c %s' % (' ' if os.path.exists(element) else '*', element))
      TRACER.log('  * - paths that do not exist or will be imported via zipimport')
      force_interpreter = 'PEX_INTERPRETER' in os.environ
      if entry_point and not force_interpreter:
        self.execute_entry(entry_point, args)
      else:
        os.unsetenv('PEX_INTERPRETER')
        TRACER.log('%s, dropping into interpreter' % (
            'PEX_INTERPRETER specified' if force_interpreter else 'No entry point specified'))
        if sys.argv[1:]:
          try:
            with open(sys.argv[1]) as fp:
              ast = compile(fp.read(), fp.name, 'exec')
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
    """
      The commandline to run this environment.

      Optional arguments:
        binary: The binary to run instead of the entry point in the environment
        interpreter_args: Arguments to be passed to the interpreter before, e.g. '-E' or
          ['-m', 'pylint.lint']
        args: Arguments to be passed to the application being invoked by the environment.
    """
    cmds = [self._interpreter.binary]
    cmds.append(self._pex)
    cmds.extend(args)
    return cmds

  def run(self, args=(), with_chroot=False, blocking=True, setsid=False):
    """
      Run the PythonEnvironment in an interpreter in a subprocess.

      with_chroot: Run with cwd set to the environment's working directory [default: False]
      blocking: If true, return the return code of the subprocess.
                If false, return the Popen object of the invoked subprocess.
    """
    import subprocess
    self.clean_environment(forking=True)

    cmdline = self.cmdline(args)
    TRACER.log('PEX.run invoking %s' % ' '.join(cmdline))
    process = subprocess.Popen(cmdline, cwd=self._pex if with_chroot else os.getcwd(),
                               preexec_fn=os.setsid if setsid else None)
    return process.wait() if blocking else process
