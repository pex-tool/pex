# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""pex support for interacting with interpreters."""

from __future__ import absolute_import

import os
import re
import sys
from collections import defaultdict
from inspect import getsource

from pex.compatibility import string
from pex.executor import Executor
from pex.pep425tags import (
    get_abbr_impl,
    get_abi_tag,
    get_config_var,
    get_flag,
    get_impl_ver,
    get_impl_version_info
)
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.tracer import TRACER

try:
  from numbers import Integral
except ImportError:
  Integral = (int, long)


ID_PY_TMPL = b"""\
import sys
import sysconfig
import warnings

__CODE__


print(
  "%s %s %s %s %s %s" % (
    get_abbr_impl(),
    get_abi_tag(),
    get_impl_ver(),
    sys.version_info[0],
    sys.version_info[1],
    sys.version_info[2]
  )
)

"""


def _generate_identity_source():
  # Determine in the most platform-compatible way possible the identity of the interpreter
  # and its known packages.
  encodables = (
    get_flag,
    get_config_var,
    get_abbr_impl,
    get_abi_tag,
    get_impl_version_info,
    get_impl_ver
  )

  return ID_PY_TMPL.replace(b'__CODE__',
                            b'\n\n'.join(getsource(func).encode('utf-8') for func in encodables))


class PythonIdentity(object):
  class Error(Exception): pass
  class InvalidError(Error): pass
  class UnknownRequirement(Error): pass

  # TODO(wickman)  Support interpreter-specific versions, e.g. PyPy-2.2.1
  HASHBANGS = {
    'CPython': 'python%(major)d.%(minor)d',
    'Jython': 'jython',
    'PyPy': 'pypy',
    'IronPython': 'ipy',
  }

  ABBR_TO_INTERPRETER = {
    'pp': 'PyPy',
    'jy': 'Jython',
    'ip': 'IronPython',
    'cp': 'CPython',
  }

  @classmethod
  def get(cls):
    return cls(
      get_abbr_impl(),
      get_abi_tag(),
      get_impl_ver(),
      str(sys.version_info[0]),
      str(sys.version_info[1]),
      str(sys.version_info[2])
    )

  @classmethod
  def from_id_string(cls, id_string):
    TRACER.log('creating PythonIdentity from id string: %s' % id_string, V=3)
    values = str(id_string).split()
    if len(values) != 6:
      raise cls.InvalidError("Invalid id string: %s" % id_string)
    return cls(*values)

  def __init__(self, impl, abi, impl_version, major, minor, patch):
    assert impl in self.ABBR_TO_INTERPRETER, (
      'unknown interpreter: {}'.format(impl)
    )
    self._interpreter = self.ABBR_TO_INTERPRETER[impl]
    self._abbr = impl
    self._version = tuple(int(v) for v in (major, minor, patch))
    self._impl_ver = impl_version
    self._abi = abi

  @property
  def abi_tag(self):
    return self._abi

  @property
  def abbr_impl(self):
    return self._abbr

  @property
  def impl_ver(self):
    return self._impl_ver

  @property
  def interpreter(self):
    return self._interpreter

  @property
  def version(self):
    return self._version

  @property
  def version_str(self):
    return '.'.join(map(str, self.version))

  @property
  def requirement(self):
    return self.distribution.as_requirement()

  @property
  def distribution(self):
    return Distribution(project_name=self.interpreter, version=self.version_str)

  @classmethod
  def parse_requirement(cls, requirement, default_interpreter='CPython'):
    if isinstance(requirement, Requirement):
      return requirement
    elif isinstance(requirement, string):
      try:
        requirement = Requirement.parse(requirement)
      except ValueError:
        try:
          requirement = Requirement.parse('%s%s' % (default_interpreter, requirement))
        except ValueError:
          raise ValueError('Unknown requirement string: %s' % requirement)
      return requirement
    else:
      raise ValueError('Unknown requirement type: %r' % (requirement,))

  def matches(self, requirement):
    """Given a Requirement, check if this interpreter matches."""
    try:
      requirement = self.parse_requirement(requirement, self._interpreter)
    except ValueError as e:
      raise self.UnknownRequirement(str(e))
    return self.distribution in requirement

  def hashbang(self):
    hashbang_string = self.HASHBANGS.get(self.interpreter, 'CPython') % {
      'major': self._version[0],
      'minor': self._version[1],
      'patch': self._version[2],
    }
    return '#!/usr/bin/env %s' % hashbang_string

  @property
  def python(self):
    # return the python version in the format of the 'python' key for distributions
    # specifically, '2.7', '3.2', etc.
    return '%d.%d' % (self.version[0:2])

  def pkg_resources_env(self, platform_str):
    """Returns a dict that can be used in place of packaging.default_environment."""
    os_name = ''
    platform_machine = ''
    platform_release = ''
    platform_system = ''
    platform_version = ''
    sys_platform = ''

    if 'win' in platform_str:
      os_name = 'nt'
      platform_machine = 'AMD64' if '64' in platform_str else 'x86'
      platform_system = 'Windows'
      sys_platform = 'win32'
    elif 'linux' in platform_str:
      os_name = 'posix'
      platform_machine = 'x86_64' if '64' in platform_str else 'i686'
      platform_system = 'Linux'
      sys_platform = 'linux2' if self._version[0] == 2 else 'linux'
    elif 'macosx' in platform_str:
      os_name = 'posix'
      platform_str = platform_str.replace('.', '_')
      platform_machine = platform_str.split('_', 3)[-1]
      # Darwin version are macOS version + 4
      platform_release = '{}.0.0'.format(int(platform_str.split('_')[2]) + 4)
      platform_system = 'Darwin'
      platform_version = 'Darwin Kernel Version {}'.format(platform_release)
      sys_platform = 'darwin'

    return {
      'implementation_name': self.interpreter.lower(),
      'implementation_version': self.version_str,
      'os_name': os_name,
      'platform_machine': platform_machine,
      'platform_release': platform_release,
      'platform_system': platform_system,
      'platform_version': platform_version,
      'python_full_version': self.version_str,
      'platform_python_implementation': self.interpreter,
      'python_version': self.version_str[:3],
      'sys_platform': sys_platform,
    }

  def __str__(self):
    return '%s-%s.%s.%s' % (
      self._interpreter,
      self._version[0],
      self._version[1],
      self._version[2]
    )

  def __repr__(self):
    return 'PythonIdentity(%r, %r, %r, %r, %r, %r)' % (
      self.abbr_impl,
      self.abi_tag,
      self.impl_ver,
      self._version[0],
      self._version[1],
      self._version[2]
    )

  def __eq__(self, other):
    return all([isinstance(other, PythonIdentity),
                self.interpreter == other.interpreter,
                self.version == other.version])

  def __hash__(self):
    return hash((self._interpreter, self._version))


class PythonInterpreter(object):
  REGEXEN = (
    re.compile(r'jython$'),

    # NB: OSX ships python binaries named Python so we allow for capital-P.
    re.compile(r'[Pp]ython$'),

    re.compile(r'python[23]$'),
    re.compile(r'python[23].[0-9]$'),
    re.compile(r'pypy$'),
    re.compile(r'pypy-1.[0-9]$'),
  )

  CACHE = {}  # memoize executable => PythonInterpreter

  class Error(Exception): pass
  class IdentificationError(Error): pass
  class InterpreterNotFound(Error): pass

  @classmethod
  def get(cls):
    return cls.from_binary(sys.executable)

  @classmethod
  def all(cls, paths=None):
    if paths is None:
      paths = os.getenv('PATH', '').split(':')
    return cls.filter(cls.find(paths))

  @classmethod
  def _from_binary_internal(cls):
    return cls(sys.executable, PythonIdentity.get())

  @classmethod
  def _from_binary_external(cls, binary):
    environ = cls.sanitized_environment()
    stdout, _ = Executor.execute([binary, '-sE'],
                                 env=environ,
                                 stdin_payload=_generate_identity_source())
    identity = stdout.strip()
    if not identity:
      raise cls.IdentificationError('Could not establish identity of %s' % binary)
    return cls(binary, PythonIdentity.from_id_string(identity))

  @classmethod
  def expand_path(cls, path):
    if os.path.isfile(path):
      return [path]
    elif os.path.isdir(path):
      return [os.path.join(path, fn) for fn in os.listdir(path)]
    return []

  @classmethod
  def from_env(cls, hashbang):
    """Resolve a PythonInterpreter as /usr/bin/env would.

       :param hashbang: A string, e.g. "python3.3" representing some binary on the $PATH.
    """
    paths = os.getenv('PATH', '').split(':')
    for path in paths:
      for fn in cls.expand_path(path):
        basefile = os.path.basename(fn)
        if hashbang == basefile:
          try:
            return cls.from_binary(fn)
          except Exception as e:
            TRACER.log('Could not identify %s: %s' % (fn, e))

  @classmethod
  def from_binary(cls, binary):
    """Create an interpreter from the given `binary`.

    :param str binary: The path to the python interpreter binary.
    :return: an interpreter created from the given `binary` with only the specified
             extras.
    :rtype: :class:`PythonInterpreter`
    """
    if binary not in cls.CACHE:
      if binary == sys.executable:
        cls.CACHE[binary] = cls._from_binary_internal()
      else:
        cls.CACHE[binary] = cls._from_binary_external(binary)
    return cls.CACHE[binary]

  @classmethod
  def _matches_binary_name(cls, basefile):
    return any(matcher.match(basefile) is not None for matcher in cls.REGEXEN)

  @classmethod
  def find(cls, paths):
    """
      Given a list of files or directories, try to detect python interpreters amongst them.
      Returns a list of PythonInterpreter objects.
    """
    pythons = []
    for path in paths:
      for fn in cls.expand_path(path):
        basefile = os.path.basename(fn)
        if cls._matches_binary_name(basefile):
          try:
            pythons.append(cls.from_binary(fn))
          except Exception as e:
            TRACER.log('Could not identify %s: %s' % (fn, e))
            continue
    return pythons

  @classmethod
  def filter(cls, pythons):
    """
      Given a map of python interpreters in the format provided by PythonInterpreter.find(),
      filter out duplicate versions and versions we would prefer not to use.

      Returns a map in the same format as find.
    """
    good = []

    MAJOR, MINOR, SUBMINOR = range(3)
    def version_filter(version):
      return (version[MAJOR] == 2 and version[MINOR] >= 7 or
              version[MAJOR] == 3 and version[MINOR] >= 4)

    all_versions = set(interpreter.identity.version for interpreter in pythons)
    good_versions = filter(version_filter, all_versions)

    for version in good_versions:
      # For each candidate, use the latest version we find on the filesystem.
      candidates = defaultdict(list)
      for interp in pythons:
        if interp.identity.version == version:
          candidates[interp.identity.interpreter].append(interp)
      for interp_class in candidates:
        candidates[interp_class].sort(
            key=lambda interp: os.path.getmtime(interp.binary), reverse=True)
        good.append(candidates[interp_class].pop(0))

    return good

  @classmethod
  def sanitized_environment(cls):
    # N.B. This is merely a hack because sysconfig.py on the default OS X
    # installation of 2.7 breaks.
    env_copy = os.environ.copy()
    env_copy.pop('MACOSX_DEPLOYMENT_TARGET', None)
    return env_copy

  def __init__(self, binary, identity):
    """Construct a PythonInterpreter.

       You should probably PythonInterpreter.from_binary instead.

       :param binary: The full path of the python binary.
       :param identity: The :class:`PythonIdentity` of the PythonInterpreter.
    """
    self._binary = os.path.realpath(binary)
    self._identity = identity

  @property
  def binary(self):
    return self._binary

  @property
  def identity(self):
    return self._identity

  @property
  def python(self):
    return self._identity.python

  @property
  def version(self):
    return self._identity.version

  @property
  def version_string(self):
    return str(self._identity)

  def __hash__(self):
    return hash((self._binary, self._identity))

  def __eq__(self, other):
    if not isinstance(other, PythonInterpreter):
      return False
    return (self._binary, self._identity) == (other._binary, other._identity)

  def __lt__(self, other):
    if not isinstance(other, PythonInterpreter):
      return False
    return self.version < other.version

  def __repr__(self):
    return '%s(%r, %r)' % (self.__class__.__name__, self._binary, self._identity)
