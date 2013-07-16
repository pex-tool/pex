from __future__ import print_function

import os
import pkg_resources
import subprocess
import sys
import tempfile

from twitter.common.dirutil import safe_mkdtemp, safe_rmtree

from .interpreter import PythonInterpreter
from .tracer import TRACER

from pkg_resources import Distribution, PathMetadata


class Installer(object):
  """
    Install an unpacked distribution with a setup.py.

    Simple example:
      >>> from twitter.common.python.http import Web, SourceLink
      >>> tornado_tgz = SourceLink('http://pypi.python.org/packages/source/t/tornado/tornado-2.3.tar.gz',
      ...                          opener=Web())
      >>> tornado_installer = Installer(tornado_tgz.fetch())
      >>> tornado_installer.distribution()
      tornado 2.3 (/private/var/folders/Uh/UhXpeRIeFfGF7HoogOKC+++++TI/-Tmp-/tmpLLe_Ph/lib/python2.6/site-packages)

    You can then take that distribution and activate it:
      >>> tornado_distribution = tornado_installer.distribution()
      >>> tornado_distribution.activate()
      >>> import tornado

    Alternately you can pass the distribution to a Distiller object and convert it to an egg:
      >>> from twitter.common.python.distiller import Distiller
      >>> Distiller(tornado_distribution).distill()
      '/var/folders/Uh/UhXpeRIeFfGF7HoogOKC+++++TI/-Tmp-/tmpufgZOO/tornado-2.3-py2.6.egg'
  """

  SETUP_BOOTSTRAP = """
if '%(setuptools_path)s':
  import sys
  sys.path.insert(0, '%(setuptools_path)s')
  import setuptools
__file__ = '%(setup_py)s'
exec(compile(open(__file__).read().replace('\\r\\n', '\\n'), __file__, 'exec'))
"""

  class InstallFailure(Exception): pass

  def __init__(self, source_dir, strict=True, interpreter=None):
    """
      Create an installer from an unpacked source distribution in source_dir.

      If strict=True, fail if any installation dependencies (e.g. distribute)
      are missing.
    """
    self._source_dir = source_dir
    self._install_tmp = safe_mkdtemp()
    self._installed = None
    self._strict = strict
    self._interpreter = interpreter or PythonInterpreter.get()
    fd, self._install_record = tempfile.mkstemp()
    os.close(fd)

  def after_installation(function):
    def function_wrapper(self, *args, **kw):
      self._installed = self.run()
      if not self._installed:
        raise Installer.InstallFailure('Failed to install %s' % self._source_dir)
      return function(self, *args, **kw)
    return function_wrapper

  def run(self):
    if self._installed is not None:
      return self._installed

    if self._interpreter.distribute is None and self._strict:
      self._installed = False
      print('Failed to find distribute in sys.path!', file=sys.stderr)
      return self._installed

    setup_bootstrap = Installer.SETUP_BOOTSTRAP % {
      'setuptools_path': self._interpreter.distribute or '',
      'setup_py': 'setup.py'
    }
    with TRACER.timed('Installing %s' % self._install_tmp, V=2):
      po = subprocess.Popen(
        [self._interpreter.binary,
          '-',
          'install',
          '--root=%s' % self._install_tmp,
          '--prefix=',
          '--single-version-externally-managed',
          '--record', self._install_record],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=self._source_dir)
      so, se = po.communicate(setup_bootstrap.encode('ascii'))
      self._installed = po.returncode == 0
    self._egg_info = None

    if not self._installed:
      print('Failed to install stdout:\n%s' % so.decode('utf-8'), file=sys.stderr)
      print('Failed to install stderr:\n%s' % se.decode('utf-8'), file=sys.stderr)
      return self._installed

    installed_files = []
    egg_info = None
    with open(self._install_record) as fp:
      installed_files = fp.read().splitlines()
      for line in installed_files:
        if line.endswith('.egg-info'):
          assert line.startswith('/'), 'Expect .egg-info to be within install_tmp!'
          egg_info = line
          break

    if not egg_info:
      self._installed = False
      return self._installed

    installed_files = [os.path.relpath(fn, egg_info) for fn in installed_files if fn != egg_info]

    self._egg_info = os.path.join(self._install_tmp, egg_info[1:])
    with open(os.path.join(self._egg_info, 'installed-files.txt'), 'w') as fp:
      fp.write('\n'.join(installed_files))
      fp.write('\n')

    return self._installed

  @after_installation
  def egg_info(self):
    return self._egg_info

  @after_installation
  def root(self):
    egg_info = self.egg_info()
    assert egg_info
    return os.path.realpath(os.path.dirname(egg_info))

  @after_installation
  def distribution(self):
    base_dir = self.root()
    egg_info = self.egg_info()
    metadata = PathMetadata(base_dir, egg_info)
    return Distribution.from_location(base_dir, os.path.basename(egg_info), metadata=metadata)

  def cleanup(self):
    safe_rmtree(self._install_tmp)

  del after_installation
