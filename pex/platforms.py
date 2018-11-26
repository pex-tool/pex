# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import namedtuple

from pex.pep425tags import (
    get_abbr_impl,
    get_abi_tag,
    get_impl_ver,
    get_platform,
    get_supported,
    get_supported_for_any_abi
)


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
      tags = get_supported_for_any_abi(
        platform=self.platform,
        impl=interpreter.identity.abbr_impl,
        version=interpreter.identity.impl_ver,
        force_manylinux=force_manylinux
      )
    else:
      tags = get_supported(
        platform=self.platform,
        impl=self.impl,
        version=self.version,
        abi=self.abi,
        force_manylinux=force_manylinux
      )

    return tags
