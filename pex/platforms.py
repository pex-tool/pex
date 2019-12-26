# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import namedtuple
from textwrap import dedent

from pex.interpreter import PythonInterpreter


class Platform(namedtuple('Platform', ['platform', 'impl', 'version', 'abi'])):
  """Represents a target platform and it's extended interpreter compatibility
  tags (e.g. implementation, version and ABI)."""

  class InvalidPlatformError(Exception):
    """Indicates an invalid platform string."""

  SEP = '-'

  @classmethod
  def create(cls, platform):
    if isinstance(platform, Platform):
      return platform

    platform = platform.lower()
    try:
      platform, impl, version, abi = platform.rsplit(cls.SEP, 3)
      return cls(platform, impl, version, abi)
    except ValueError:
      raise cls.InvalidPlatformError(dedent("""\
        Not a valid platform specifier: {}

        Platform strings must be in one of two forms:
        1. Canonical: <platform>-<python impl abbr>-<python version>-<abi>
        2. Abbreviated: <platform>-<python impl abbr>-<python version>-<abbr abi>

        Given a canonical platform string for CPython 3.7.5 running on 64 bit linux of:
          linux-x86_64-cp-37-cp37m

        Where the fields above are:
        + <platform>: linux-x86_64 
        + <python impl abbr>: cp
        + <python version>: 37
        + <abi>: cp37m

        The abbreviated platform string is:
          linux-x86_64-cp-37-m

        These fields stem from wheel name conventions as outlined in
        https://www.python.org/dev/peps/pep-0427#file-name-convention and influenced by
        https://www.python.org/dev/peps/pep-0425.
        """.format(platform)))

  @staticmethod
  def _maybe_prefix_abi(impl, version, abi):
    if impl != 'cp':
      return abi
    # N.B. This permits CPython users to pass in simpler extended platform
    # strings like `linux-x86_64-cp-27-mu` vs e.g. `linux-x86_64-cp-27-cp27mu`.
    impl_ver = ''.join((impl, version))
    return abi if abi.startswith(impl_ver) else ''.join((impl_ver, abi))

  def __new__(cls, platform, impl, version, abi):
    if not all((platform, impl, version, abi)):
      raise cls.InvalidPlatformError(
        'Platform specifiers cannot have blank fields. Given platform={platform!r}, impl={impl!r}, '
        'version={version!r}, abi={abi!r}'.format(
          platform=platform, impl=impl, version=version, abi=abi
        )
      )
    platform = platform.replace('-', '_').replace('.', '_')
    abi = cls._maybe_prefix_abi(impl, version, abi)
    return super(Platform, cls).__new__(cls, platform, impl, version, abi)

  @classmethod
  def of_interpreter(cls, intepreter=None):
    intepreter = intepreter or PythonInterpreter.get()
    identity = intepreter.identity
    impl, version = identity.python_tag[:2], identity.python_tag[2:]
    return cls(platform=identity.platform_tag,
               impl=impl,
               version=version,
               abi=identity.abi_tag)

  @classmethod
  def current(cls):
    return cls.of_interpreter()

  def __str__(self):
    return self.SEP.join(self)
