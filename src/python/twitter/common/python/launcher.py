# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import errno
import os
import sys
import json
import runpy
import signal
import subprocess

from twitter.common.python.dirwrapper import PythonDirectoryWrapper
from twitter.common.python.eggcache import EggCache
from twitter.common.collections import OrderedSet
from twitter.common.contextutil import pushd, environment_as

def start_coverage():
  try:
    import coverage
    cov = coverage.coverage(auto_data=True, data_suffix=True,
      data_file='.coverage.%s' % os.environ['PEX_COVERAGE'])
    cov.start()
  except ImportError:
    sys.stderr.write('Could not bootstrap coverage module!\n')

class PythonLauncher(object):
  """
    An execution wrapper around a serialized PythonEnvironment.
  """
  class NotFound(Exception): pass
  class InvalidFormat(Exception): pass

  MANIFEST = 'PEX-INFO'

  def __init__(self, path):
    if not os.path.exists(path):
      raise PythonLauncher.NotFound("Could not find python environment in %s" % path)
    self._dir = PythonDirectoryWrapper.get(path)
    try:
      self._manifest = json.loads(self._dir.read(PythonLauncher.MANIFEST))
    except ValueError, e:
      raise PythonLauncher.InvalidFormat("Could not parse manifest! %s" % e)
    self._cache = EggCache(self._dir)
    self._path = OrderedSet([os.path.abspath(path)])

  @staticmethod
  def debug(msg):
    if os.environ.has_key('PEX_VERBOSE'):
      print >> sys.stderr, 'PEX: %s' % msg

  def entry(self):
    """
      Return the module spec of the entry point of this PythonEnvironment.  None if
      there is no binary for this environment.
    """
    if os.environ.has_key('PEX_MODULE'):
      return os.environ['PEX_MODULE']
    entry_point = self._manifest.get('entry', None)
    if entry_point:
      return str(entry_point)

  def binary(self):
    """
      Translate the entry point module spec into its equivalent python script.
    """
    entry_point = self.entry()
    if entry_point is None:
      return None
    entry_point = os.path.sep.join(entry_point.split('.'))
    return '%s.py' % entry_point

  def execute(self):
    entry_point = self.entry()
    saved_sys_path = sys.path[:]
    # TODO(John Sirois): plumb this through all the way to the BUILD
    # files so that "thin" targets may specify this by default.
    if os.environ.has_key('PEX_INHERIT_PATH'):
      sys.path.extend(self.path())
    else:
      sys.path = self.path()
    if os.environ.has_key('PEX_COVERAGE'):
      start_coverage()
    PythonLauncher.debug('Initialized sys.path to %s' % ':'.join(sys.path))
    force_interpreter = os.environ.has_key('PEX_INTERPRETER')
    if entry_point and not force_interpreter:
      PythonLauncher.debug('Detected entry_point: %s' % entry_point)
      runpy.run_module(entry_point, run_name='__main__')
    else:
      PythonLauncher.debug('%s, dropping into interpreter' % (
        'PEX_INTERPRETER specified' if force_interpreter else 'No entry point specified.'))
      if sys.argv[1:]:
        self.run(args=sys.argv[1:])
      else:
        import code
        code.interact()
    sys.path = saved_sys_path

  @staticmethod
  def minimum_path():
    """
      Return the emulated sys.path of a bare python installation, so that we
      can try to mimick python -S without actually calling python -S (which
      would be ideal but doesn't play well with virtualenvs with rely upon
      site manipulation.)
    """
    import sys, site
    from distutils.sysconfig import get_python_lib
    save_sys_path = sys.path[:]
    try:
      site_packages_prefix = get_python_lib()
      site_packages = set()
      site.addsitepackages(site_packages)
      scrub_from_sys_path = filter(lambda pkg: \
        pkg in site_packages or site_packages_prefix in pkg,
        sys.path)
      for path in scrub_from_sys_path:
        PythonLauncher.debug('Scrubbing from sys.path: %s' % path)
      scrubbed_sys_path = list(OrderedSet(sys.path) - OrderedSet(scrub_from_sys_path))
    finally:
      sys.path = save_sys_path
    return scrubbed_sys_path

  def path(self, extras=[]):
    """
      Return the sys.path necessary to run this environment.
    """
    p = OrderedSet(self._path)
    p.update(self._cache.paths())
    p.update(extras)
    p.update(PythonLauncher.minimum_path())
    return list(p)

  def cmdline(self, binary=None, interpreter_args=[], args=[]):
    """
      The commandline to run this environment.

      Optional arguments:
        binary: The binary to run instead of the entry point as specified in the environment.
        interpreter_args: Arguments to be passed to the interpreter before, e.g. '-E' or
          ['-m', 'pylint.lint']
        args: Arguments to be passed to the application being invoked by the environment.
    """
    cmds = [sys.executable]
    cmds.extend(interpreter_args)
    if binary is None: binary = self.binary()
    if binary: cmds.append(os.path.join(self._dir.path(), binary))
    cmds.extend(args)
    return cmds

  def run(self, binary=None, interpreter_args=[], args=[], extra_deps=[], with_chroot=False,
      kill_orphans=False):
    """
      Run the PythonEnvironment in an interpreter in a subprocess.
    """
    cmdline = self.cmdline(binary, interpreter_args, args)
    path = self.path(extras=extra_deps)

    with pushd(self._dir.path() if with_chroot else os.getcwd()):
      with environment_as(PYTHONPATH=':'.join(path)):
        PythonLauncher.debug('With PYTHONPATH=%s, executing %s' % (
          ':'.join(path), ' '.join(cmdline)))
        # Spawn in a new session so we can cleanup any orphans
        po = subprocess.Popen(cmdline, preexec_fn=os.setsid)

        rv = -1
        try:
          rv = po.wait()
        finally:
          if kill_orphans and rv:
            self._reap_orphans(po.pid)

    return rv

  def _reap_orphans(self, pid):
    try:
      os.killpg(pid, signal.SIGTERM)
    except OSError as e:
      # It is not unexpected that all children exited normally
      if e.errno == errno.EPERM:
        PythonLauncher.debug("Unable to kill process group: %d" % pid)
        return
      if e.errno != errno.ESRCH:
        raise
