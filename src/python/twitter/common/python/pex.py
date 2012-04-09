from __future__ import print_function

import contextlib
import os
import sys
import time

from twitter.common.contextutil import mutable_sys
from twitter.common.lang import Compatibility
from twitter.common.python.dirwrapper import PythonDirectoryWrapper
from twitter.common.python.interpreter import PythonInterpreter
from twitter.common.python.pex_info import PexInfo
from twitter.common.python.resolver import Resolver
from twitter.common.python.util import DistributionHelper

class PEX(object):
  """
    PEX, n. A self-contained python environment.
  """
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
  def debug(cls, msg):
    if 'PEX_VERBOSE' in os.environ:
      print('PEX: %s' % msg, file=sys.stderr)

  @classmethod
  @contextlib.contextmanager
  def timed(cls, prefix):
    start_time = time.time()
    yield
    end_time = time.time()
    cls.debug('%s => %.3fms' % (prefix, 1000.0 * (end_time - start_time)))

  def __init__(self, pex=sys.argv[0]):
    self._pex = PythonDirectoryWrapper.get(pex)
    self._pex_info = PexInfo.from_pex(self._pex)
    self._env = PEXEnvironment(self._pex.path(), self._pex_info)

  def entry(self):
    """
      Return the module spec of the entry point of this PEX.  None if there
      is no entry point for this environment.
    """
    if 'PEX_MODULE' in os.environ:
      self.debug('PEX_MODULE override detected: %s' % os.environ['PEX_MODULE'])
      return os.environ['PEX_MODULE']
    entry_point = self._pex_info.entry_point
    if entry_point:
      self.debug('Using prescribed entry point: %s' % entry_point)
      return str(entry_point)

  @classmethod
  def minimum_path(cls):
    """
      Return as a tuple the emulated sys.path and sys.path_importer_cache of
      a bare python installation, a la python -S.
    """
    from site import USER_SITE
    from twitter.common.collections import OrderedSet
    from pkg_resources import find_distributions
    from distutils.sysconfig import get_python_lib
    site_libs = set([get_python_lib(plat_specific=False), get_python_lib(plat_specific=True)])
    site_distributions = OrderedSet()
    for path_element in sys.path:
      if any(path_element.startswith(site_lib) for site_lib in site_libs):
        cls.debug('Inspecting path element: %s' % path_element)
        site_distributions.update(dist.location for dist in find_distributions(path_element))
    user_site_distributions = OrderedSet(dist.location for dist in find_distributions(USER_SITE))
    for path in site_distributions:
      cls.debug('Scrubbing from site-packages: %s' % path)
    for path in user_site_distributions:
      cls.debug('Scrubbing from user site: %s' % path)
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
      self.debug('PYTHONPATH now %s' % ':'.join(sys.path))
      force_interpreter = 'PEX_INTERPRETER' in os.environ
      if entry_point and not force_interpreter:
        self.execute_entry(entry_point, args)
      else:
        self.debug('%s, dropping into interpreter' % ('PEX_INTERPRETER specified' if force_interpreter
           else 'No entry point specified.'))
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
            Compatibility.exec_function(ast, globals())
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
    runner(entry_point)

  @staticmethod
  def execute_module(module_name):
    import runpy
    runpy.run_module(module_name, run_name='__main__')

  @staticmethod
  def execute_pkg_resources(spec):
    from pkg_resources import EntryPoint
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
    interpreter = PythonInterpreter(sys.executable)
    cmds = [interpreter.binary()]
    cmds.append(self._pex.path())
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

    cmdline = self.cmdline(args)
    self.debug('PEX.run invoking %s' % ' '.join(cmdline))
    process = subprocess.Popen(cmdline, cwd = self._pex.path() if with_chroot else os.getcwd(),
                               preexec_fn = os.setsid if setsid else None)
    return process.wait() if blocking else process


class PEXEnvironment(Resolver):
  @classmethod
  def _log(cls, msg, *args, **kw):
    PEX.debug(msg)

  def __init__(self, pex, pex_info):
    self._pex_info = pex_info
    subcaches = sum([
      [os.path.join(pex, pex_info.internal_cache)],
      [cache for cache in pex_info.egg_caches],
      [pex_info.install_cache if pex_info.install_cache else []]],
      [])
    self._activated = False
    super(PEXEnvironment, self).__init__(
      caches=subcaches,
      install_cache=pex_info.install_cache,
      fetcher_provider=PEXEnvironment.get_fetcher_provider(pex_info))

  @classmethod
  def get_fetcher_provider(cls, pex_info):
    def fetcher_provider():
      from twitter.common.python.fetcher import Fetcher
      cls._log('Initializing fetcher:')
      cls._log('  repositories: %s' % ' '.join(pex_info.repositories))
      cls._log('       indices: %s' % ' '.join(pex_info.indices))
      cls._log('     with pypi: %s' % pex_info.allow_pypi)
      return Fetcher(
        repositories = pex_info.repositories,
        indices = pex_info.indices,
        external = pex_info.allow_pypi,
        download_cache = pex_info.download_cache
      )
    return fetcher_provider

  @staticmethod
  def _really_zipsafe(dist):
    try:
      pez_info = dist.resource_listdir('/PEZ-INFO')
    except OSError:
      pez_info = []
    if 'zip-safe' in pez_info:
      return True
    egg_metadata = dist.metadata_listdir('/')
    return 'zip-safe' in egg_metadata and 'native_libs.txt' not in egg_metadata

  def activate(self):
    from pkg_resources import Requirement, WorkingSet, DistributionNotFound

    if self._activated:
      return
    if self._pex_info.inherit_path:
      self._ws = WorkingSet(sys.path)

    # TODO(wickman)  Implement dynamic fetchers if pex_info requirements specify dynamic=True
    # or a non-empty repository.
    all_reqs = [Requirement.parse(req) for req, _, _ in self._pex_info.requirements]

    for req in all_reqs:
      with PEX.timed('Resolved %s' % str(req)):
        try:
          resolved = self._ws.resolve([req], env=self)
        except DistributionNotFound as e:
          self._log('Failed to resolve %s: %s' % (req, e))
          if not self._pex_info.ignore_errors:
            raise
          continue
      for dist in resolved:
        with PEX.timed('  Activated %s' % dist):
          if self._really_zipsafe(dist):
            self._ws.add(dist)
            dist.activate()
          else:
            with PEX.timed('    Locally caching %s' % dist):
              new_dist = DistributionHelper.locally_cache(dist, self._pex_info.install_cache)
              new_dist.activate()

    self._activated = True
