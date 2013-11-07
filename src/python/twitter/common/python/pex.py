from __future__ import absolute_import, print_function

import contextlib
from distutils import sysconfig
from hashlib import sha1
import os
import shutil
from site import USER_SITE
import sys
import uuid
import zipfile


from .base import maybe_requirement_list
from .common import mutable_sys, open_zip, safe_mkdir, safe_rmtree
from .compatibility import exec_function
from .dirwrapper import PythonDirectoryWrapper
from .interpreter import PythonInterpreter
from .orderedset import OrderedSet
from .pex_info import PexInfo
from .platforms import Platform
from .tracer import Tracer
from .util import DistributionHelper

from pkg_resources import (
    DistributionNotFound,
    EntryPoint,
    Environment,
    Requirement,
    WorkingSet,
    find_distributions,
)

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
    try:
      self._pex = PythonDirectoryWrapper.get(pex)
    except PythonDirectoryWrapper.Error as e:
      raise self.NotFound('Could not open PEX at %s: %s!' % (pex, e))
    self._pex_info = PexInfo.from_pex(self._pex)
    self._env = PEXEnvironment(self._pex.path(), self._pex_info)
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
        TRACER.log('Inspecting path element: %s' % path_element)
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
      TRACER.log('PYTHONPATH now %s' % ':'.join(sys.path))
      force_interpreter = 'PEX_INTERPRETER' in os.environ
      if entry_point and not force_interpreter:
        self.execute_entry(entry_point, args)
      else:
        os.unsetenv('PEX_INTERPRETER')
        TRACER.log('%s, dropping into interpreter' % (
            'PEX_INTERPRETER specified' if force_interpreter else 'No entry point specified.'))
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
      pstats.Stats(profile_output).sort_stats(
          os.environ.get('PEX_PROFILE_SORT', 'cumulative')).print_stats(1000)

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
    self.clean_environment(forking=True)

    cmdline = self.cmdline(args)
    TRACER.log('PEX.run invoking %s' % ' '.join(cmdline))
    process = subprocess.Popen(cmdline, cwd = self._pex.path() if with_chroot else os.getcwd(),
                               preexec_fn = os.setsid if setsid else None)
    return process.wait() if blocking else process


class PEXEnvironment(Environment):
  class Subcache(object):
    def __init__(self, path, env):
      self._activated = False
      self._path = path
      self._env = env

    @property
    def activated(self):
      return self._activated

    def activate(self):
      if not self._activated:
        with TRACER.timed('Activating cache %s' % self._path):
          for dist in find_distributions(self._path):
            if self._env.can_add(dist):
              with TRACER.timed('Adding %s:%s' % (dist, dist.location)):
                self._env.add(dist)
        self._activated = True

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

  @staticmethod
  def _hash_digest(filename, hasher=sha1):
    file_hash = hasher()
    block_size = file_hash.block_size * 1024
    with open(filename, 'rb') as fh:
      for chunk in iter(lambda: fh.read(block_size), ''):
        file_hash.update(chunk)
    return file_hash.hexdigest()

  @classmethod
  def resolve_internal_cache(cls, pex, pex_info):
    # TODO(wickman) this logic is duplicated in pex_bootstrapper.py -- consider factoring it out
    if os.path.exists(os.path.join(pex, pex_info.internal_cache)) or (
        not pex_info.always_write_cache):
      return os.path.join(pex, pex_info.internal_cache)

    # we assume the pex is a zip, so write that instead.
    with contextlib.closing(zipfile.ZipFile(pex)) as zf:
      for zi in zf.infolist():
        if zi.filename.endswith('/') or not zi.filename.startswith(pex_info.internal_cache):
          # either it's a directory or not part of our cache
          continue
        relpath = os.path.relpath(zi.filename, pex_info.internal_cache)
        target_path = os.path.join(pex_info.egg_install_cache, relpath)
        if os.path.exists(target_path) and os.path.getsize(target_path) == zi.file_size:
          # assume already cached
          continue
        safe_mkdir(os.path.dirname(target_path))
        with TRACER.timed('Extracting %s' % target_path):
          with open(target_path + '~', 'wb') as dst_fp:
            with contextlib.closing(zf.open(zi.filename)) as src_fp:
              shutil.copyfileobj(src_fp, dst_fp)
        os.rename(target_path + '~', target_path)
      return pex_info.egg_install_cache

  def __init__(self, pex, pex_info, platform=Platform.current(), python=Platform.python()):
    with TRACER.timed('Establishing local cache'):
      internal_cache = self.resolve_internal_cache(pex, pex_info)
    subcaches = sum([
      [internal_cache],
      [cache for cache in pex_info.egg_caches],
      # TODO(wickman) We should create a symlink overlay of pex_install so as to not get
      # non-deterministic dependency creep.
      [pex_info.install_cache if pex_info.install_cache else []]],
      [])
    self._pex = pex
    self._pex_info = pex_info
    self._activated = False
    self._subcaches = [self.Subcache(cache, self) for cache in subcaches]
    self._ws = WorkingSet([])
    with TRACER.timed('Calling environment super'):
      super(PEXEnvironment, self).__init__(search_path=[], platform=platform, python=python)

  def resolve(self, requirements, ignore_errors=False):
    reqs = maybe_requirement_list(requirements)
    resolved = OrderedSet()
    for req in reqs:
      with TRACER.timed('Resolving %s' % req):
        try:
          distributions = self._ws.resolve([req], env=self)
        except DistributionNotFound as e:
          TRACER.log('Failed to resolve %s: %s' % (req, e))
          if not ignore_errors:
            raise
          continue
        resolved.update(distributions)
    return list(resolved)

  def can_add(self, dist):
    return Platform.distribution_compatible(dist, self.python, self.platform)

  def best_match(self, req, *ignore_args, **ignore_kwargs):
    while True:
      resolved_req = super(PEXEnvironment, self).best_match(req, self._ws)
      if resolved_req:
        return resolved_req
      for subcache in self._subcaches:
        if not subcache.activated:
          subcache.activate()
          break
      else:
        # TODO(wickman)  Add per-requirement optional/ignore_errors flag.
        print('Failed to resolve %s, your installation may not work properly.' % req,
            file=sys.stderr)
        break

  def activate(self):
    if self._activated:
      return

    if os.environ.get('PEX_FORCE_LOCAL', not self._pex_info.zip_safe) and os.path.isfile(self._pex):
      pex_chksum = self._hash_digest(self._pex)
      explode_dir = os.path.join(self._pex_info.zip_unsafe_cache, pex_chksum)
      TRACER.log('zip_safe is False, explode_dir: %s' % explode_dir)
      if not os.path.exists(explode_dir):
        explode_tmp = explode_dir + '.' + uuid.uuid4().hex
        with TRACER.timed('Unzipping %s' % self._pex):
          try:
            safe_mkdir(explode_tmp)
            with open_zip(self._pex) as pex_zip:
              pex_files = (x for x in pex_zip.namelist() if not x.startswith('.'))
              pex_zip.extractall(explode_tmp, pex_files)
          except:
            safe_rmtree(explode_tmp)
            raise
        TRACER.log('Renaming %s to %s' % (explode_tmp, explode_dir))
        os.rename(explode_tmp, explode_dir)

      # Force subsequent imports to come from the .pex directory rather than the .pex file.
      TRACER.log('Adding to the head of sys.path: %s' % explode_dir)
      sys.path.insert(0, explode_dir)
      for name, module in sys.modules.items():
        if hasattr(module, "__path__"):
          module_dir = os.path.join(explode_dir, *name.split("."))
          TRACER.log('Adding to the head of %s.__path__: %s' % (module.__name__, module_dir))
          module.__path__.insert(0, module_dir)

    if self._pex_info.inherit_path:
      self._ws = WorkingSet(sys.path)

    # TODO(wickman)  Implement dynamic fetchers if pex_info requirements specify dynamic=True
    # or a non-empty repository.
    all_reqs = [Requirement.parse(req) for req, _, _ in self._pex_info.requirements]

    for req in all_reqs:
      with TRACER.timed('Resolving %s' % req):
        try:
          resolved = self._ws.resolve([req], env=self)
        except DistributionNotFound as e:
          TRACER.log('Failed to resolve %s: %s' % (req, e))
          if not self._pex_info.ignore_errors:
            raise
          continue
      for dist in resolved:
        with TRACER.timed('Activated %s' % dist):
          if os.environ.get('PEX_FORCE_LOCAL', not self._really_zipsafe(dist)):
            with TRACER.timed('Locally caching'):
              new_dist = DistributionHelper.maybe_locally_cache(dist, self._pex_info.install_cache)
              new_dist.activate()
          else:
            self._ws.add(dist)
            dist.activate()

    self._activated = True
