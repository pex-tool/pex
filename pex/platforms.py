# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import namedtuple
from textwrap import dedent

from pex.pep425tags import get_abbr_impl, get_abi_tag, get_impl_ver, get_platform, get_supported


def _gen_all_compatible_versions(version):
  # We select major and minor here in the context of implementation version strings.
  # These are typically two digit characters; eg "27" or "36", but they can be three digit
  # characters in the case of pypy; eg "271". In the typical case the 1st digit represents the
  # python major version and the 2nd digit it's minor version. In the pypy case, the 1st digit still
  # represents the (hosting) python major version, the 2nd the pypy major version and the 3rd the
  # pypy minor version. In both cases the last digit is the minor version and the python in question
  # guarantees backwards compatibility of minor version bumps within the major version as per
  # semver and PEP 425 (https://www.python.org/dev/peps/pep-0425/#id1).
  #
  # Concrete examples of what we want to return in each case:
  # 1. typical case of cpython "36": ["36", "35", "34", "33", "32", "31", "30"]
  # 2. pypy case of "271": ["271", "270"].
  #
  # For more information on the pypy case see conversation here:
  #   https://github.com/pypa/pip/issues/2882
  # In particular https://github.com/pypa/pip/issues/2882#issuecomment-110925458 and
  # https://github.com/pypa/pip/issues/2882#issuecomment-130404840.
  # The fix work for pip handling of this is done here: https://github.com/pypa/pip/pull/3075

  major, minor = version[:-1], version[-1]

  def iter_compatible_versions():
    # Support all previous minor Python versions.
    for compatible_minor in range(int(minor), -1, -1):
      yield '{major}{minor}'.format(major=major, minor=compatible_minor)

  return list(iter_compatible_versions())


class Platform(namedtuple('Platform', ['platform', 'impl', 'version', 'abi'])):
  """Represents a target platform and it's extended interpreter compatibility
  tags (e.g. implementation, version and ABI)."""

  class InvalidPlatformError(Exception):
    """Indicates an invalid platform string."""

  SEP = '-'

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

  def __str__(self):
    return self.SEP.join(self)

  @classmethod
  def current(cls):
    platform = get_platform()
    impl = get_abbr_impl()
    version = get_impl_ver()
    abi = get_abi_tag()
    return cls(platform, impl, version, abi)

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

  @classmethod
  def of_interpreter(cls, intepreter=None):
    if intepreter is None:
      return cls.current()

    return cls(platform=get_platform(),
               impl=intepreter.identity.abbr_impl,
               version=intepreter.identity.impl_ver,
               abi=intepreter.identity.abi_tag)

  @staticmethod
  def _maybe_prefix_abi(impl, version, abi):
    if impl != 'cp':
      return abi
    # N.B. This permits CPython users to pass in simpler extended platform
    # strings like `linux-x86_64-cp-27-mu` vs e.g. `linux-x86_64-cp-27-cp27mu`.
    impl_ver = ''.join((impl, version))
    return abi if abi.startswith(impl_ver) else ''.join((impl_ver, abi))

  def supported_tags(self):
    """Returns a list of supported PEP425 tags for the current platform."""
    if self == self.current():
      return get_supported()

    return get_supported(
      versions=_gen_all_compatible_versions(self.version),
      platform=self.platform,
      impl=self.impl,
      abi=self.abi
    )
