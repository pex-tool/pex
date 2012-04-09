from __future__ import print_function

import os
import pkg_resources
import subprocess
import sys
import tempfile
from pkg_resources import Distribution, PathMetadata, require

from twitter.common.dirutil import safe_rmtree

class Installer(object):
  """
    Install an unpacked distribution with a setup.py.

    Simple example:
      >>> from twitter.common.python.installer import Fetcher, Installer
      >>> pypi = Fetcher.pypi()
      >>> celery_installer = Installer(pypi.fetch('celery>2.4'))  # this takes several seconds
      >>> celery_installer.distribution()
      celery 2.5.0 (/private/var/folders/Uh/UhXpeRIeFfGF7HoogOKC+++++TI/-Tmp-/tmpaWRGGW/lib/python2.6/site-packages)

    You can then take that distribution and activate it:
      >>> celery_distribution = celery_installer.distribution()
      >>> celery_distribution.activate()
      >>> import celery

    Alternately you can pass celery_distribution to a Distiller object and convert it to an egg:
      >>> from twitter.common.python.distiller import Distiller
      >>> Distiller(celery_distribution).distill()
      '/var/folders/Uh/UhXpeRIeFfGF7HoogOKC+++++TI/-Tmp-/tmp1KPNEE/celery-2.5.0-py2.6.egg'
  """


  SETUP_BOOTSTRAP = """
import sys
sys.path.insert(0, '%(setuptools_path)s')
import setuptools
__file__ = '%(setup_py)s'
exec(compile(open(__file__).read().replace('\\r\\n', '\\n'), __file__, 'exec'))
"""

  class InstallFailure(Exception): pass

  def __init__(self, source_dir):
    self._source_dir = source_dir
    self._install_tmp = tempfile.mkdtemp()
    self._installed = None
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
    setuptools_path = None
    for item in sys.path:
      for dist in pkg_resources.find_distributions(item):
        if dist.project_name == 'distribute':
          setuptools_path = dist.location
          break

    if setuptools_path is None:
      self._installed = False
      print('Failed to find distribute in sys.path!', file=sys.stderr)
      return self._installed

    setup_bootstrap = Installer.SETUP_BOOTSTRAP % {
      'setuptools_path': setuptools_path,
      'setup_py': 'setup.py'
    }
    po = subprocess.Popen(
      [sys.executable,
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
