# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import namedtuple

from pex.orderedset import OrderedSet
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


def _get_supported(version=None, platform=None, impl=None, abi=None, force_manylinux=False):
  versions = _gen_all_compatible_versions(version) if version is not None else None
  all_supported = get_supported(
    versions=versions,
    platform=platform,
    impl=impl,
    abi=abi
  )

  def iter_all_supported():
    for supported in all_supported:
      yield supported
      python_tag, abi_tag, platform_tag = supported
      if platform_tag.startswith('linux') and force_manylinux:
        yield python_tag, abi_tag, platform_tag.replace('linux', 'manylinux1')

  return list(OrderedSet(iter_all_supported()))


def _gen_all_abis(impl, version):
  def tmpl_abi(impl, version, suffix):
    return ''.join((impl, version, suffix))
  yield tmpl_abi(impl, version, 'd')
  yield tmpl_abi(impl, version, 'dm')
  yield tmpl_abi(impl, version, 'dmu')
  yield tmpl_abi(impl, version, 'm')
  yield tmpl_abi(impl, version, 'mu')
  yield tmpl_abi(impl, version, 'u')


def _get_supported_for_any_abi(version=None, platform=None, impl=None, force_manylinux=False):
  """Generates supported tags for unspecified ABI types to support more intuitive cross-platform
     resolution."""
  unique_tags = {
    tag for abi in _gen_all_abis(impl, version)
    for tag in _get_supported(version=version,
                              platform=platform,
                              impl=impl,
                              abi=abi,
                              force_manylinux=force_manylinux)
  }
  return list(unique_tags)


class Platform(namedtuple('Platform', ['platform', 'impl', 'version', 'abi'])):
  """Represents a target platform and it's extended interpreter compatibility
  tags (e.g. implementation, version and ABI)."""

  SEP = '-'

  def __new__(cls, platform, impl=None, version=None, abi=None):
    platform = platform.replace('-', '_').replace('.', '_')
    if all((impl, version, abi)):
      abi = cls._maybe_prefix_abi(impl, version, abi)
    return super(cls, Platform).__new__(cls, platform, impl, version, abi)

  def __str__(self):
    return self.SEP.join(self) if all(self) else self.platform

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
    if platform == 'current':
      return cls.current()

    try:
      platform, impl, version, abi = platform.rsplit(cls.SEP, 3)
    except ValueError:
      return cls(platform)
    else:
      return cls(platform, impl, version, abi)

  @staticmethod
  def _maybe_prefix_abi(impl, version, abi):
    if impl != 'cp':
      return abi
    # N.B. This permits CPython users to pass in simpler extended platform
    # strings like `linux-x86_64-cp-27-mu` vs e.g. `linux-x86_64-cp-27-cp27mu`.
    impl_ver = ''.join((impl, version))
    return abi if abi.startswith(impl_ver) else ''.join((impl_ver, abi))

  @property
  def is_extended(self):
    return all(attr is not None for attr in (self.impl, self.version, self.abi))

  def supported_tags(self, interpreter=None, force_manylinux=True):
    """Returns a list of supported PEP425 tags for the current platform."""
    if interpreter and not self.is_extended:
      # N.B. If we don't get an extended platform specifier, we generate
      # all possible ABI permutations to mimic earlier pex version
      # behavior and make cross-platform resolution more intuitive.
      return _get_supported_for_any_abi(
        platform=self.platform,
        impl=interpreter.identity.abbr_impl,
        version=interpreter.identity.impl_ver,
        force_manylinux=force_manylinux
      )
    else:
      return _get_supported(
        platform=self.platform,
        impl=self.impl,
        version=self.version,
        abi=self.abi,
        force_manylinux=force_manylinux
      )
