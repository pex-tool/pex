# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import json
import os
import sys
import warnings
from collections import namedtuple

from .common import open_zip
from .compatibility import string as compatibility_string
from .orderedset import OrderedSet

PexPlatform = namedtuple('PexPlatform', 'interpreter version strict')


class PexInfo(object):
  """PEX metadata.

  # Build metadata:
  build_properties: BuildProperties # (key-value information about the build system)
  code_hash: str                    # sha1 hash of all names/code in the archive
  distributions: {dist_name: str}   # map from distribution name (i.e. path in
                                    # the internal cache) to its cache key (sha1)

  # Environment options
  pex_root: ~/.pex                   # root of all pex-related files
  entry_point: string                # entry point into this pex
  zip_safe: True, default False      # is this pex zip safe?
  inherit_path: True, default False  # should this pex inherit site-packages + PYTHONPATH?
  ignore_errors: True, default False # should we ignore inability to resolve dependencies?
  always_write_cache: False          # should we always write the internal cache to disk first?
                                     # this is useful if you have very large dependencies that
                                     # do not fit in RAM constrained environments
  requirements: list                 # list of requirements for this environment


  .. versionchanged:: 0.8
    Removed the ``repositories`` and ``indices`` information, as they were never
    implemented.
  """

  PATH = 'PEX-INFO'
  INTERNAL_CACHE = '.deps'

  @classmethod
  def make_build_properties(cls):
    from .interpreter import PythonInterpreter
    from pkg_resources import get_platform

    pi = PythonInterpreter.get()
    return {
      'class': pi.identity.interpreter,
      'version': pi.identity.version,
      'platform': get_platform(),
    }

  @classmethod
  def default(cls):
    pex_info = {
      'requirements': [],
      'distributions': {},
      'always_write_cache': False,
      'build_properties': cls.make_build_properties(),
    }
    return cls(info=pex_info)

  @classmethod
  def from_pex(cls, pex):
    if os.path.isfile(pex):
      with open_zip(pex) as zf:
        pex_info = zf.read(cls.PATH)
    else:
      with open(os.path.join(pex, cls.PATH)) as fp:
        pex_info = fp.read()
    return cls.from_json(pex_info)

  @classmethod
  def from_json(cls, content):
    if isinstance(content, bytes):
      content = content.decode('utf-8')
    return PexInfo(info=json.loads(content))

  @classmethod
  def _parse_requirement_tuple(cls, requirement_tuple):
    if isinstance(requirement_tuple, (tuple, list)):
      if len(requirement_tuple) != 3:
        raise ValueError('Malformed PEX requirement: %r' % (requirement_tuple,))
      # pre 0.8.x requirement type:
      warnings.warn('Attempting to use deprecated PEX feature.  Please upgrade past PEX 0.8.x.')
      return requirement_tuple[0]
    elif isinstance(requirement_tuple, compatibility_string):
      return requirement_tuple
    raise ValueError('Malformed PEX requirement: %r' % (requirement_tuple,))

  @classmethod
  def debug(cls, msg):
    if 'PEX_VERBOSE' in os.environ:
      print('PEX: %s' % msg, file=sys.stderr)

  def __init__(self, info=None):
    """Construct a new PexInfo.  This should not be used directly."""

    if info is not None and not isinstance(info, dict):
      raise ValueError('PexInfo can only be seeded with a dict, got: '
                       '%s of type %s' % (info, type(info)))
    self._pex_info = info or {}
    self._distributions = self._pex_info.get('distributions', {})
    requirements = self._pex_info.get('requirements', [])
    if not isinstance(requirements, (list, tuple)):
      raise ValueError('Expected requirements to be a list, got %s' % type(requirements))
    self._requirements = OrderedSet(self._parse_requirement_tuple(req) for req in requirements)

  @property
  def build_properties(self):
    """Information about the system on which this PEX was generated.

    :returns: A dictionary containing metadata about the environment used to build this PEX.
    """
    return self._pex_info.get('build_properties', {})

  @build_properties.setter
  def build_properties(self, value):
    if not isinstance(value, dict):
      raise TypeError('build_properties must be a dictionary!')
    self._pex_info['build_properties'] = self.make_build_properties()
    self._pex_info['build_properties'].update(value)

  @property
  def zip_safe(self):
    """Whether or not this PEX should be treated as zip-safe.

    If set to false and the PEX is zipped, the contents of the PEX will be unpacked into a
    directory within the PEX_ROOT prior to execution.  This allows code and frameworks depending
    upon __file__ existing on disk to operate normally.

    By default zip_safe is True.  May be overridden at runtime by the $PEX_FORCE_LOCAL environment
    variable.
    """
    if 'PEX_FORCE_LOCAL' in os.environ:
      self.debug('PEX_FORCE_LOCAL forcing zip_safe to False')
      return False
    return self._pex_info.get('zip_safe', True)

  @zip_safe.setter
  def zip_safe(self, value):
    self._pex_info['zip_safe'] = bool(value)

  @property
  def inherit_path(self):
    """Whether or not this PEX should be allowed to inherit system dependencies.

    By default, PEX environments are scrubbed of all system distributions prior to execution.
    This means that PEX files cannot rely upon preexisting system libraries.

    By default inherit_path is False.  This may be overridden at runtime by the $PEX_INHERIT_PATH
    environment variable.
    """
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
  def code_hash(self):
    return self._pex_info.get('code_hash')

  @code_hash.setter
  def code_hash(self, value):
    self._pex_info['code_hash'] = value

  @property
  def entry_point(self):
    if 'PEX_MODULE' in os.environ:
      self.debug('PEX_MODULE override detected: %s' % os.environ['PEX_MODULE'])
      return os.environ['PEX_MODULE']
    return self._pex_info.get('entry_point')

  @entry_point.setter
  def entry_point(self, value):
    self._pex_info['entry_point'] = value

  def add_requirement(self, requirement):
    self._requirements.add(str(requirement))

  @property
  def requirements(self):
    return self._requirements

  def add_distribution(self, location, sha):
    self._distributions[location] = sha

  @property
  def distributions(self):
    return self._distributions

  @property
  def always_write_cache(self):
    if 'PEX_ALWAYS_CACHE' in os.environ:
      self.debug('PEX_ALWAYS_CACHE override detected: %s' % os.environ['PEX_ALWAYS_CACHE'])
      return True
    return self._pex_info.get('always_write_cache', False)

  @always_write_cache.setter
  def always_write_cache(self, value):
    self._pex_info['always_write_cache'] = bool(value)

  @property
  def pex_root(self):
    pex_root = self._pex_info.get('pex_root', os.path.join('~', '.pex'))
    return os.path.expanduser(os.environ.get('PEX_ROOT', pex_root))

  @pex_root.setter
  def pex_root(self, value):
    self._pex_info['pex_root'] = value

  @property
  def internal_cache(self):
    return self.INTERNAL_CACHE

  @property
  def install_cache(self):
    return os.path.join(self.pex_root, 'install')

  @property
  def zip_unsafe_cache(self):
    return os.path.join(self.pex_root, 'code')

  def dump(self):
    pex_info_copy = self._pex_info.copy()
    pex_info_copy['requirements'] = list(self._requirements)
    return json.dumps(pex_info_copy)

  def copy(self):
    return PexInfo(info=self._pex_info.copy())
