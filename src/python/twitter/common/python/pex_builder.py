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

import os
import pkg_resources
import sys
import tempfile
from pkg_resources import (
  Distribution,
  DistributionNotFound,
  EggMetadata)

from twitter.common.lang import Compatibility
from twitter.common.dirutil import chmod_plus_x
from twitter.common.dirutil.chroot import Chroot
from twitter.common.python.importer import EggZipImporter
from twitter.common.python.interpreter import PythonIdentity
from twitter.common.python.marshaller import CodeMarshaller
from twitter.common.python.pex_info import PexInfo
from twitter.common.python.pex import PEX
from twitter.common.python.util import DistributionHelper

BOOTSTRAP_ENVIRONMENT = b"""
import os
import sys

__entry_point__ = None
if '__file__' in locals() and __file__ is not None:
  __entry_point__ = os.path.dirname(__file__)
elif '__loader__' in locals():
  from zipimport import zipimporter
  from pkgutil import ImpLoader
  #if isinstance(__loader__, (builtin_zipimport.zipimporter, EggZipImporter)):
  if hasattr(__loader__, 'archive'):
    __entry_point__ = __loader__.archive
  elif isinstance(__loader__, ImpLoader):
    __entry_point__ = os.path.dirname(__loader__.get_filename())

if __entry_point__ is None:
  sys.stderr.write('Could not launch python executable!\\n')
  sys.exit(2)

sys.path[0] = os.path.abspath(sys.path[0])
sys.path.insert(0, os.path.abspath(os.path.join(__entry_point__, '.bootstrap')))

from twitter.common.python.importer import monkeypatch
monkeypatch()
del monkeypatch

from twitter.common.python.pex import PEX
PEX(__entry_point__).execute()
"""


class PEXBuilder(object):
  class InvalidDependency(Exception): pass
  class InvalidExecutableSpecification(Exception): pass

  DEPENDENCY_DIR = ".deps"
  BOOTSTRAP_DIR = ".bootstrap"

  def __init__(self, path=None):
    self._chroot = Chroot(path or tempfile.mkdtemp())
    self._pex_info = PexInfo.default()
    self._frozen = False

  def chroot(self):
    return self._chroot

  def path(self):
    return self.chroot().path()

  def info(self):
    return self._pex_info

  def add_source(self, filename, env_filename):
    self._chroot.link(filename, env_filename, "source")
    if filename.endswith('.py'):
      env_filename_pyc = os.path.splitext(env_filename)[0] + '.pyc'
      # with PEX.timed('Compiling %s' % env_filename_pyc):
      with open(filename) as fp:
        pyc_object = CodeMarshaller.from_py(fp.read(), env_filename)
      self._chroot.write(pyc_object.to_pyc(), env_filename_pyc, 'source')

  def add_resource(self, filename, env_filename):
    self._chroot.link(filename, env_filename, "resource")

  def add_requirement(self, req, dynamic=False, repo=None):
    self._pex_info.add_requirement(req, repo=repo, dynamic=dynamic)

  def add_dependency_file(self, filename, env_filename):
    # TODO(wickman) This is broken.  The build cache abstraction just breaks down here.
    if filename.endswith('.egg'):
      self.add_egg(filename)
    else:
      self._chroot.link(filename, os.path.join(PEXBuilder.DEPENDENCY_DIR, env_filename))

  def add_egg(self, egg):
    """
      helper for add_distribution
    """
    metadata = EggMetadata(EggZipImporter(egg))
    dist = Distribution.from_filename(egg, metadata)
    self.add_distribution(dist)
    self.add_requirement(dist.as_requirement(), dynamic=False, repo=None)

  def add_distribution(self, dist):
    if not dist.location.endswith('.egg'):
      raise PEXBuilder.InvalidDependency('Non-egg dependencies not yet supported.')
    self._chroot.link(dist.location,
      os.path.join(PEXBuilder.DEPENDENCY_DIR, os.path.basename(dist.location)))

  def set_executable(self, filename, env_filename=None):
    if env_filename is None:
      env_filename = os.path.basename(filename)
    if self._chroot.get("executable"):
      raise PEXBuilder.InvalidExecutableSpecification(
          "Setting executable on a PEXBuilder that already has one!")
    self._chroot.link(filename, env_filename, "executable")
    entry_point = env_filename
    entry_point.replace(os.path.sep, '.')
    self._pex_info.entry_point = entry_point.rpartition('.')[0]

  def _prepare_inits(self):
    relative_digest = self._chroot.get("source")
    init_digest = set()
    for path in relative_digest:
      split_path = path.split(os.path.sep)
      for k in range(1, len(split_path)):
        sub_path = os.path.sep.join(split_path[0:k] + ['__init__.py'])
        if sub_path not in relative_digest and sub_path not in init_digest:
          self._chroot.touch(sub_path)
          init_digest.add(sub_path)

  def _prepare_manifest(self):
    self._chroot.write(self._pex_info.dump().encode('utf-8'), PexInfo.PATH, label='manifest')

  def _prepare_main(self):
    self._chroot.write(BOOTSTRAP_ENVIRONMENT, '__main__.py', label='main')

  def _prepare_bootstrap(self):
    """
      Write enough of distribute and pip into the .pex .bootstrap directory so that
      we can be fully self-contained.
    """
    bare_env = pkg_resources.Environment()

    pip_req = pkg_resources.Requirement.parse('pip>=1.1')
    distribute_req = pkg_resources.Requirement.parse('distribute>=0.6.24')
    pip_dist = distribute_dist = None

    for dist in DistributionHelper.all_distributions(sys.path):
      if dist in pip_req and bare_env.can_add(dist):
        pip_dist = dist
      if dist in distribute_req and bare_env.can_add(dist):
        distribute_dist = dist
      if pip_dist and distribute_dist:
        break
    if not pip_dist:
      raise DistributionNotFound('Could not find pip!')
    if not distribute_dist:
      raise DistributionNotFound('Could not find distribute!')

    PEX.debug('Writing .bootstrap library.')
    for fn, content in DistributionHelper.walk_data(pip_dist):
      if fn.startswith('pip/'):
        # PEX.debug('BOOTSTRAP: Writing %s' % fn)
        self._chroot.write(content, os.path.join(self.BOOTSTRAP_DIR, fn), 'resource')
    for fn, content in DistributionHelper.walk_data(distribute_dist):
      if fn.startswith('pkg_resources.py') or fn.startswith('setuptools'):
        # PEX.debug('BOOTSTRAP: Writing %s' % fn)
        self._chroot.write(content, os.path.join(self.BOOTSTRAP_DIR, fn), 'resource')
    libraries = (
      'twitter.common.dirutil',
      'twitter.common.collections',
      'twitter.common.contextutil',
      'twitter.common.lang',
      'twitter.common.python'
    )
    for name in libraries:
      dirname = name.replace('.', '/')
      provider = pkg_resources.get_provider(name)
      if not isinstance(provider, pkg_resources.DefaultProvider):
        mod = __import__(name, fromlist=['wutttt'])
        provider = pkg_resources.ZipProvider(mod)
      for fn in provider.resource_listdir(''):
        if fn.endswith('.py'):
          # PEX.debug('BOOTSTRAP: Writing %s' % os.path.join(dirname, fn))
          self._chroot.write(provider.get_resource_string(name, fn),
            os.path.join(self.BOOTSTRAP_DIR, dirname, fn), 'resource')
    for initdir in ('twitter', 'twitter/common'):
      self._chroot.write(
        b"__import__('pkg_resources').declare_namespace(__name__)",
        os.path.join(self.BOOTSTRAP_DIR, initdir, '__init__.py'),
        'resource')

  def freeze(self):
    if self._frozen:
      return
    self._prepare_inits()
    self._prepare_manifest()
    self._prepare_bootstrap()
    self._prepare_main()
    self._frozen = True

  def build(self, filename):
    self.freeze()
    try:
      os.unlink(filename + '~')
      print('WARNING: Previous binary unexpectedly exists, cleaning: %s' % (filename + '~'))
    except OSError:
      # The expectation is that the file does not exist, so continue
      pass
    with open(filename + '~', 'ab') as pexfile:
      assert os.path.getsize(pexfile.name) == 0
      # TODO(wickman) Make this tunable
      pexfile.write(Compatibility.to_bytes('%s\n' % PythonIdentity.get().hashbang()))
    self._chroot.zip(filename + '~', mode='a')
    if os.path.exists(filename):
      os.unlink(filename)
    os.rename(filename + '~', filename)
    chmod_plus_x(filename)
