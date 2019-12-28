# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""pex support for interacting with interpreters."""

from __future__ import absolute_import

import json
import os
import re
import sys
from textwrap import dedent

from pex import third_party
from pex.compatibility import string
from pex.executor import Executor
from pex.third_party.packaging import markers, tags
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.tracer import TRACER


class PythonIdentity(object):
  class Error(Exception): pass
  class InvalidError(Error): pass
  class UnknownRequirement(Error): pass

  # TODO(wickman)  Support interpreter-specific versions, e.g. PyPy-2.2.1
  INTERPRETER_NAME_TO_HASHBANG = {
    'CPython': 'python%(major)d.%(minor)d',
    'Jython': 'jython',
    'PyPy': 'pypy',
    'IronPython': 'ipy',
  }

  ABBR_TO_INTERPRETER_NAME = {
    'pp': 'PyPy',
    'jy': 'Jython',
    'ip': 'IronPython',
    'cp': 'CPython',
  }

  @classmethod
  def get(cls):
    supported_tags = tuple(tags.sys_tags())
    preferred_tag = supported_tags[0]
    return cls(
      python_tag=preferred_tag.interpreter,
      abi_tag=preferred_tag.abi,
      platform_tag=preferred_tag.platform,
      version=sys.version_info[:3],
      supported_tags=supported_tags,
      env_markers=markers.default_environment()
    )

  @classmethod
  def decode(cls, encoded):
    TRACER.log('creating PythonIdentity from encoded: %s' % encoded, V=9)
    values = json.loads(encoded)
    if len(values) != 6:
      raise cls.InvalidError("Invalid id string: %s" % encoded)

    supported_tags = values.pop('supported_tags')

    def iter_tags():
      for supported_tag in supported_tags:
        yield tags.Tag(
          interpreter=supported_tag['interpreter'],
          abi=supported_tag['abi'],
          platform=supported_tag['platform']
        )

    return cls(supported_tags=iter_tags(), **values)

  @classmethod
  def _find_interpreter_name(cls, python_tag):
    for abbr, interpreter in cls.ABBR_TO_INTERPRETER_NAME.items():
      if python_tag.startswith(abbr):
        return interpreter
    raise ValueError('Unknown interpreter: {}'.format(python_tag))

  def __init__(self, python_tag, abi_tag, platform_tag, version, supported_tags, env_markers):
    # N.B.: We keep this mapping to support historical values for `distribution` and `requirement`
    # properties.
    self._interpreter_name = self._find_interpreter_name(python_tag)

    self._python_tag = python_tag
    self._abi_tag = abi_tag
    self._platform_tag = platform_tag
    self._version = tuple(version)
    self._supported_tags = tuple(supported_tags)
    self._env_markers = dict(env_markers)

  def encode(self):
    values = dict(
      python_tag=self._python_tag,
      abi_tag=self._abi_tag,
      platform_tag=self._platform_tag,
      version=self._version,
      supported_tags=[
        dict(interpreter=tag.interpreter, abi=tag.abi, platform=tag.platform)
        for tag in self._supported_tags
      ],
      env_markers=self._env_markers
    )
    return json.dumps(values)

  @property
  def python_tag(self):
    return self._python_tag

  @property
  def abi_tag(self):
    return self._abi_tag

  @property
  def platform_tag(self):
    return self._platform_tag

  @property
  def version(self):
    return self._version

  @property
  def version_str(self):
    return '.'.join(map(str, self.version))

  @property
  def supported_tags(self):
    return self._supported_tags

  @property
  def env_markers(self):
    return dict(self._env_markers)

  @property
  def interpreter(self):
    return self._interpreter_name

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
      requirement = self.parse_requirement(requirement, self._interpreter_name)
    except ValueError as e:
      raise self.UnknownRequirement(str(e))
    return self.distribution in requirement

  def hashbang(self):
    hashbang_string = self.INTERPRETER_NAME_TO_HASHBANG.get(self._interpreter_name, 'CPython') % {
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

  def __str__(self):
    return '%s-%s.%s.%s' % (
      self._interpreter_name,
      self._version[0],
      self._version[1],
      self._version[2]
    )

  def _tup(self):
    return self._python_tag, self._abi_tag, self._platform_tag, self._version

  def __eq__(self, other):
    if type(other) is not type(self):
      return NotImplemented
    return self._tup() == other._tup()

  def __hash__(self):
    return hash(self._tup())


class PythonInterpreter(object):
  REGEXEN = (
    re.compile(r'jython$'),

    # NB: OSX ships python binaries named Python so we allow for capital-P.
    re.compile(r'[Pp]ython$'),

    re.compile(r'python[23]$'),
    re.compile(r'python[23].[0-9]$'),

    # Some distributions include a suffix on the in the interpreter name, similar to PEP-3149
    # E.g. Gentoo has /usr/bin/python3.6m to indicate it was built with pymalloc
    re.compile(r'python[23].[0-9][a-z]$'),

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
  def iter(cls, paths=None):
    """Iterate all interpreters found in `paths`.

    NB: The paths can either be directories to search for python binaries or the paths of python
    binaries themselves.

    :param paths: The paths to look for python interpreters; by default the `PATH`.
    :type paths: list str
    """
    if paths is None:
      paths = os.getenv('PATH', '').split(os.pathsep)
    for interpreter in cls._filter(cls._find(paths)):
      yield interpreter

  @classmethod
  def all(cls, paths=None):
    return list(cls.iter(paths=paths))

  @classmethod
  def _from_binary_internal(cls):
    return cls(sys.executable, PythonIdentity.get())

  @classmethod
  def _create_isolated_cmd(cls, binary, args=None, pythonpath=None, env=None):
    cmd = [binary]

    # Don't add the user site directory to `sys.path`.
    #
    # Additionally, it would be nice to pass `-S` to disable adding site-packages but unfortunately
    # some python distributions include portions of the standard library there.
    cmd.append('-s')

    env = cls.sanitized_environment(env=env)
    pythonpath = list(pythonpath or ())
    if pythonpath:
      env['PYTHONPATH'] = os.pathsep.join(pythonpath)
    else:
      # Turn off reading of PYTHON* environment variables.
      cmd.append('-E')

    if args:
      cmd.extend(args)

    rendered_command = ' '.join(cmd)
    if pythonpath:
      rendered_command = 'PYTHONPATH={} {}'.format(env['PYTHONPATH'], rendered_command)
    TRACER.log('Executing: {}'.format(rendered_command), V=3)

    return cmd, env

  @classmethod
  def _execute(cls, binary, args=None, pythonpath=None, env=None, stdin_payload=None, **kwargs):
    cmd, env = cls._create_isolated_cmd(binary, args=args, pythonpath=pythonpath, env=env)
    stdout, stderr = Executor.execute(cmd, stdin_payload=stdin_payload, env=env, **kwargs)
    return cmd, stdout, stderr

  @classmethod
  def _from_binary_external(cls, binary):
    pythonpath = third_party.expose(['pex'])
    _, stdout, _ = cls._execute(
      binary,
      args=[
        '-c',
        dedent("""\
        import sys
        from pex.interpreter import PythonIdentity

        sys.stdout.write(PythonIdentity.get().encode())
        """)
      ],
      pythonpath=pythonpath
    )
    identity = stdout.strip()
    if not identity:
      raise cls.IdentificationError('Could not establish identity of %s' % binary)
    return cls(binary, PythonIdentity.decode(identity))

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
    normalized_binary = os.path.realpath(binary)
    if normalized_binary not in cls.CACHE:
      if normalized_binary == os.path.realpath(sys.executable):
        cls.CACHE[normalized_binary] = cls._from_binary_internal()
      else:
        cls.CACHE[normalized_binary] = cls._from_binary_external(normalized_binary)
    return cls.CACHE[normalized_binary]

  @classmethod
  def _matches_binary_name(cls, basefile):
    return any(matcher.match(basefile) is not None for matcher in cls.REGEXEN)

  @classmethod
  def _find(cls, paths):
    """
      Given a list of files or directories, try to detect python interpreters amongst them.
      Returns an iterator over PythonInterpreter objects.
    """
    for path in paths:
      for fn in cls.expand_path(path):
        basefile = os.path.basename(fn)
        if cls._matches_binary_name(basefile):
          try:
            yield cls.from_binary(fn)
          except Exception as e:
            TRACER.log('Could not identify %s: %s' % (fn, e))
            continue

  @classmethod
  def _filter(cls, pythons):
    """
      Given an iterator over python interpreters filter out duplicate versions and versions we would
      prefer not to use.

      Returns an iterator over PythonInterpreters.
    """
    MAJOR, MINOR, SUBMINOR = range(3)
    def version_filter(version):
      return (version[MAJOR] == 2 and version[MINOR] >= 7 or
              version[MAJOR] == 3 and version[MINOR] >= 4)

    seen = set()
    for interp in pythons:
      version = interp.identity.version
      if version not in seen and version_filter(version):
        seen.add(version)
        yield interp

  @classmethod
  def sanitized_environment(cls, env=None):
    # N.B. This is merely a hack because sysconfig.py on the default OS X
    # installation of 2.7 breaks.
    env_copy = (env or os.environ).copy()
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

  def execute(self, args=None, stdin_payload=None, pythonpath=None, env=None, **kwargs):
    return self._execute(self.binary,
                         args=args,
                         stdin_payload=stdin_payload,
                         pythonpath=pythonpath,
                         env=env,
                         **kwargs)

  def open_process(self, args=None, pythonpath=None, env=None, **kwargs):
    cmd, env = self._create_isolated_cmd(self.binary, args=args, pythonpath=pythonpath, env=env)
    process = Executor.open_process(cmd, env=env, **kwargs)
    return cmd, process

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
