from __future__ import print_function

from collections import namedtuple
import json
import os
import sys
from pkg_resources import get_platform

from .interpreter import PythonInterpreter
from twitter.common.collections import OrderedSet

PexRequirement = namedtuple('PexRequirement', 'requirement repo dynamic')
PexPlatform = namedtuple('PexPlatform', 'interpreter version strict')

class PexInfo(object):
  """
    PEX metadata.

    # Build metadata:

    build_properties: BuildProperties (from pants)

    # Loader options

    entry_point: string                # entry point into this pex
    zip_safe: True, default False      # is this pex zip safe?
    inherit_path: True, default False  # should this pex inherit site-packages + PYTHONPATH?
    ignore_errors: True, default False # should we ignore inability to resolve dependencies?

    # Platform options to dictate how to interpret this pex

    target_platform: PexPlatform

    # Dependency options

    requirements: list  # list of PexRequirement tuples [requirement, repository, dynamic]
    allow_pypi: bool     # whether or not to allow fetching from pypi repos + indices + mirrors
    repositories: list   # list of default repositories
    indices: []          # list of default indices
    egg_caches: []       # list of egg caches
    download_cache: path # path to use for a download cache; do not cache downloads if empty
    install_cache: path  # path to use for install cache; do not distill+cache installs if empty
  """

  PATH = 'PEX-INFO'

  # TODO(wickman) This probably belongs in pants, not in here?
  @classmethod
  def make_build_properties(cls):
    pi = PythonInterpreter()
    base_info = {
      'class': pi.identity().interpreter,
      'version': pi.identity().version,
      'platform': get_platform(),
    }
    try:
      from twitter.pants.base.build_info import get_build_info
      base_info.update(get_build_info()._asdict())
    except ImportError:
      pass
    return base_info

  @classmethod
  def default(cls):
    pi = PythonInterpreter()
    pex_info = {
      'requirements': [],
      'build_properties': cls.make_build_properties(),
    }
    return cls(json.dumps(pex_info))

  @classmethod
  def from_pex(cls, pex):
    return cls(pex.read(cls.PATH))

  @classmethod
  def debug(cls, msg):
    if 'PEX_VERBOSE' in os.environ:
      print('PEX: %s' % msg, file=sys.stderr)

  def __init__(self, content=json.dumps({})):
    if isinstance(content, bytes):
      content = content.decode('utf-8')
    self._pex_info = json.loads(content)
    self._requirements = OrderedSet(
        PexRequirement(*req) for req in self._pex_info.get('requirements', []))
    self._repositories = OrderedSet(self._pex_info.get('repositories', []))
    self._indices = OrderedSet(self._pex_info.get('indices', []))
    self._egg_caches = OrderedSet(self._pex_info.get('egg_caches', []))

  @property
  def build_properties(self):
    return self._pex_info.get('build_properties', {})

  @property
  def zip_safe(self):
    return self._pex_info.get('zip_safe', True)

  @zip_safe.setter
  def zip_safe(self, value):
    self._pex_info['zip_safe'] = bool(value)

  @property
  def inherit_path(self):
    if 'PEX_INHERIT_PATH' in os.environ:
      self.debug('PEX_INHERIT_PATH override detected')
      return True
    else:
      return self._pex_info.get('inherit_path', False)

  @inherit_path.setter
  def inherit_path(self, value):
    self._pex_info['inherit_path'] = bool(value)

  @property
  def ignore_errors(self):
    return self._pex_info.get('ignore_errors', False)

  @ignore_errors.setter
  def ignore_errors(self, value):
    self._pex_info['ignore_errors'] = bool(value)

  @property
  def entry_point(self):
    if 'PEX_MODULE' in os.environ:
      self.debug('PEX_MODULE override detected: %s' % os.environ['PEX_MODULE'])
      return os.environ['PEX_MODULE']
    return self._pex_info.get('entry_point')

  @entry_point.setter
  def entry_point(self, value):
    self._pex_info['entry_point'] = value

  def add_requirement(self, requirement, repo=None, dynamic=False):
    self._requirements.add(PexRequirement(str(requirement), repo, dynamic))

  @property
  def requirements(self):
    return self._requirements

  @property
  def allow_pypi(self):
    return self._pex_info.get('allow_pypi', False)

  @allow_pypi.setter
  def allow_pypi(self, value):
    self._pex_info['allow_pypi'] = bool(value)

  def add_repository(self, repo):
    self._repositories.add(repo)

  @property
  def repositories(self):
    return self._repositories

  def add_index(self, index):
    self._indices.add(index)

  @property
  def indices(self):
    return self._indices

  def add_egg_cache(self, egg_cache):
    self._egg_caches.add(egg_cache)

  @property
  def egg_caches(self):
    return self._egg_caches

  @property
  def internal_cache(self):
    return self._pex_info.get('internal_cache', '.deps')

  @internal_cache.setter
  def internal_cache(self, value):
    self._pex_info['internal_cache'] = value

  @property
  def install_cache(self):
    return self._pex_info.get('install_cache',
      os.path.expanduser(os.path.join('~', '.pex', 'install')))

  @install_cache.setter
  def install_cache(self, value):
    self._pex_info['install_cache'] = value

  @property
  def download_cache(self):
    return self._pex_info.get('download_cache',
      os.path.expanduser(os.path.join('~', '.pex', 'download')))

  @download_cache.setter
  def download_cache(self, value):
    self._pex_info['download_cache'] = value

  def dump(self):
    pex_info_copy = self._pex_info.copy()
    pex_info_copy['requirements'] = list(self._requirements)
    pex_info_copy['indices'] = list(self._indices)
    pex_info_copy['repositories'] = list(self._repositories)
    pex_info_copy['egg_caches'] = list(self._egg_caches)
    return json.dumps(pex_info_copy)
