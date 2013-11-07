"""
twitter.common.python support for interpreter environments.
"""
from __future__ import absolute_import

try:
  from numbers import Integral
except ImportError:
  Integral = (int, long)

from collections import defaultdict
import os
import re
import subprocess
import sys

from .tracer import Tracer

from pkg_resources import find_distributions, Distribution, Requirement

TRACER = Tracer(predicate=Tracer.env_filter('PEX_VERBOSE'),
    prefix='twitter.common.python.interpreter: ')


# Determine in the most platform-compatible way possible the identity of the interpreter
# and whether or not it has a distribute egg.
ID_PY = b"""
import sys

if hasattr(sys, 'subversion'):
  subversion = sys.subversion[0]
else:
  subversion = 'CPython'

setuptools_path = None
try:
  import pkg_resources
  try:
    setuptools_req = pkg_resources.Requirement.parse('setuptools>=1', replacement=False)
  except TypeError:
    setuptools_req = pkg_resources.Requirement.parse('setuptools>=1')
  for item in sys.path:
    for dist in pkg_resources.find_distributions(item):
      if dist in setuptools_req:
        setuptools_path = dist.location
        break
except ImportError:
  pass

print("%s %s %s %s" % (
  subversion,
  sys.version_info[0],
  sys.version_info[1],
  sys.version_info[2]))
print(setuptools_path)
"""


class PythonIdentity(object):
  class Error(Exception): pass
  class InvalidError(Error): pass
  class UnknownRequirement(Error): pass

  @staticmethod
  def get():
    if hasattr(sys, 'subversion'):
      subversion = sys.subversion[0]
    else:
      subversion = 'CPython'
    return PythonIdentity(subversion, sys.version_info[0], sys.version_info[1], sys.version_info[2])

  @classmethod
  def from_id_string(cls, id_string):
    values = id_string.split()
    if len(values) != 4:
      raise cls.InvalidError("Invalid id string: %s" % id_string)
    return cls(str(values[0]), int(values[1]), int(values[2]), int(values[3]))

  @classmethod
  def from_path(cls, dirname):
    interp, version = dirname.split('-')
    major, minor, patch = version.split('.')
    return cls(str(interp), int(major), int(minor), int(patch))

  def __init__(self, interpreter, major, minor, patch):
    for var in (major, minor, patch):
      assert isinstance(var, Integral)
    self._interpreter = interpreter
    self._version = (major, minor, patch)

  @property
  def interpreter(self):
    return self._interpreter

  @property
  def version(self):
    return self._version

  @property
  def requirement(self):
    return self.distribution.as_requirement()

  @property
  def distribution(self):
    return Distribution(project_name=self._interpreter, version='.'.join(map(str, self._version)))

  @classmethod
  def parse_requirement(cls, requirement, default_interpreter='CPython'):
    if isinstance(requirement, Requirement):
      return requirement
    elif isinstance(requirement, str):
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
    return '#!/usr/bin/env python%s.%s' % self._version[0:2]

  def __str__(self):
    return '%s-%s.%s.%s' % (self._interpreter,
      self._version[0], self._version[1], self._version[2])

  def __repr__(self):
    return 'PythonIdentity(%r, %s, %s, %s)' % (
        self._interpreter, self._version[0], self._version[1], self._version[2])

  def __eq__(self, other):
    return all([isinstance(other, PythonIdentity),
                self.interpreter == other.interpreter,
                self.version == other.version])

  def __hash__(self):
    return hash((self._interpreter, self._version))


class PythonInterpreter(object):
  REGEXEN = (
    re.compile(r'jython$'),
    re.compile(r'python$'),
    re.compile(r'python[23].[0-9]$'),
    re.compile(r'pypy$'),
    re.compile(r'pypy-1.[0-9]$'),
  )

  CACHE = {}  # memoize executable => PythonInterpreter

  try:
    # Versions of distribute prior to the setuptools merge would automatically replace
    # 'setuptools' requirements with 'distribute'.  It provided the 'replacement' kwarg
    # to toggle this, but it was removed post-merge.
    COMPATIBLE_SETUPTOOLS = Requirement.parse('setuptools>=1.0', replacement=False)
  except TypeError:
    COMPATIBLE_SETUPTOOLS = Requirement.parse('setuptools>=1.0')

  class Error(Exception): pass
  class IdentificationError(Error): pass

  @classmethod
  def get(cls):
    return cls(sys.executable, interpreter=PythonIdentity.get())

  @classmethod
  def all(cls, paths=os.getenv('PATH').split(':')):
    return cls.filter(PythonInterpreter.find(paths))

  @classmethod
  def from_binary(cls, binary):
    if binary not in cls.CACHE:
      cls.sanitize_environment()
      po = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
      so, _ = po.communicate(ID_PY)
      output = so.decode('utf8').splitlines()
      if len(output) != 2:
        raise cls.IdentificationError("Could not establish identity of %s" % binary)
      id_string, distribute_path = output
      cls.CACHE[binary] = cls(binary, PythonIdentity.from_id_string(id_string),
          distribute_path=distribute_path if distribute_path != "None" else None)
    return cls.CACHE[binary]

  @classmethod
  def find(cls, paths):
    """
      Given a list of files or directories, try to detect python interpreters amongst them.
      Returns a list of PythonInterpreter objects.
    """
    pythons = []
    for path in paths:
      def expand_path(path):
        if os.path.isfile(path):
          return [path]
        elif os.path.isdir(path):
          return (os.path.join(path, fn) for fn in os.listdir(path))
        return []
      for fn in expand_path(path):
        basefile = os.path.basename(fn)
        if any(matcher.match(basefile) is not None for matcher in cls.REGEXEN):
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
      return (version[MAJOR] == 2 and version[MINOR] >= 6 or
              version[MAJOR] == 3 and version[MINOR] >= 2)

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
  def sanitize_environment(cls):
    # N.B. This is merely a hack because sysconfig.py on the default OS X
    # installation of 2.6/2.7 breaks.
    os.unsetenv('MACOSX_DEPLOYMENT_TARGET')

  @classmethod
  def replace(cls, requirement):
    self = cls.get()
    if self.identity.matches(requirement):
      return False
    for pi in cls.all():
      if pi.identity.matches(requirement):
        break
    else:
      raise cls.InterpreterNotFound('Could not find interpreter matching filter!')
    cls.sanitize_environment()
    os.execv(pi.binary, [pi.binary] + sys.argv)

  def __init__(self, binary=None, interpreter=None, distribute_path=None):
    """
      :binary => binary of python interpreter
                 (if None, default to sys.executable)
    """
    self._binary = binary or sys.executable
    self._binary_stat = os.stat(self._binary)

    if self._binary == sys.executable:
      self._identity = interpreter or PythonIdentity.get()
      self._distribute = distribute_path or self._find_distribute()
    else:
      self._identity = interpreter or PythonInterpreter.from_binary(self._binary).identity
      self._distribute = distribute_path

  def _find_distribute(self):
    for item in sys.path:
      for dist in find_distributions(item):
        if dist in self.COMPATIBLE_SETUPTOOLS:
          return dist.location

  @property
  def binary(self):
    return self._binary

  @property
  def identity(self):
    return self._identity

  @property
  def python(self):
    # return the python version in the format of the 'python' key for distributions
    # specifically, '2.6', '2.7', '3.2', etc.
    return '%d.%d' % (self._identity.version[0:2])

  @property
  def version(self):
    return self._identity.version

  @property
  def version_string(self):
    return str(self._identity)

  @property
  def distribute(self):
    return self._distribute

  def __hash__(self):
    return hash(self._binary_stat)

  def __eq__(self, other):
    if not isinstance(other, self.__class__):
      return False
    return self._binary_stat == other._binary_stat

  def __lt__(self, other):
    if not isinstance(other, self.__class__):
      return False
    return self.version < other.version

  def __repr__(self):
    return '%s(%r, %r, %r)' % (self.__class__.__name__, self._binary, self._identity,
        self._distribute)
