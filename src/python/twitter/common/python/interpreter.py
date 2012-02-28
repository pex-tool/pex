try:
  from numbers import Integral
except ImportError:
  Integral = (int, long)

import os
import re
import subprocess
import sys


if not hasattr(__builtins__, 'any'):
  def any(genexpr):
    for expr in genexpr:
      if expr:
        return True
    return False


ID_PY = b"""
import sys

if hasattr(sys, 'subversion'):
  subversion = sys.subversion[0]
else:
  subversion = 'CPython'

print("%s %s %s %s" % (
  subversion,
  sys.version_info[0],
  sys.version_info[1],
  sys.version_info[2]))
"""


class PythonIdentity(object):
  class InvalidError(Exception): pass

  @staticmethod
  def get():
    if hasattr(sys, 'subversion'):
      subversion = sys.subversion[0]
    else:
      subversion = 'CPython'
    return PythonIdentity(subversion, sys.version_info[0], sys.version_info[1], sys.version_info[2])

  @staticmethod
  def from_id_string(id_string):
    values = id_string.split()
    if len(values) != 4:
      raise PythonIdentity.InvalidError("Invalid id string: %s" % id_string)
    return PythonIdentity(str(values[0]), int(values[1]), int(values[2]), int(values[3]))

  def __init__(self, interpreter, major, minor, subminor):
    for var in (major, minor, subminor):
      assert isinstance(var, Integral)
    self._interpreter = interpreter
    self._version = (major, minor, subminor)

  @property
  def version(self):
    return self._version

  def hashbang(self):
    # TODO(wickman)  Must be a better way.
    return '#!/usr/bin/env python%s.%s' % self._version[0:2]

  def __str__(self):
    return '%s-%s.%s.%s' % (self._interpreter,
      self._version[0], self._version[1], self._version[2])

  def __repr__(self):
    return 'PythonIdentity("%s", %s, %s, %s)' % (
      self._interpreter,
      self._version[0], self._version[1], self._version[2])


class PythonInterpreter(object):
  REGEXEN = (
    re.compile(r'python$'), re.compile(r'python[23].[0-9]$'),
    re.compile(r'pypy$'), re.compile(r'pypy-1.[0-9]$'),
  )

  @staticmethod
  def get():
    return PythonInterpreter(sys.executable, interpreter=PythonIdentity.get())

  @staticmethod
  def all(paths=os.getenv('PATH').split(':')):
    return PythonInterpreter.filter(PythonInterpreter.find(paths))

  @staticmethod
  def from_binary(binary):
    po = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    so, _ = po.communicate(ID_PY)
    return PythonInterpreter(binary, PythonIdentity.from_id_string(so.decode('utf8')))

  def __init__(self, binary=sys.executable, interpreter=None):
    """
      :binary => binary of python interpreter
                 (if None, default to sys.executable)
    """
    self._binary = binary

    if binary == sys.executable and interpreter is None:
      self._identity = PythonIdentity.get()
    else:
      self._identity = interpreter or PythonInterpreter.from_binary(binary).identity()

  def binary(self):
    return self._binary

  def identity(self):
    return self._identity

  def __repr__(self):
    return 'PythonInterpreter(%r, %r)' % (self._binary, self._identity)

  @staticmethod
  def find(paths):
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
        if any(matcher.match(basefile) is not None for matcher in PythonInterpreter.REGEXEN):
          try:
            pythons.append(PythonInterpreter.from_binary(fn))
          except:
            continue
    return pythons

  @staticmethod
  def filter(pythons):
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

    all_versions = set(interpreter.identity().version for interpreter in pythons)
    good_versions = filter(version_filter, all_versions)

    for version in good_versions:
      # For each candidate, use the latest version we find on the filesystem.
      candidates = [interp for interp in pythons if interp.identity().version == version]
      candidates.sort(key=lambda interp: os.path.getmtime(interp.binary()), reverse=True)
      good.append(candidates.pop(0))

    return good
