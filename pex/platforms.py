# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import namedtuple
from textwrap import dedent

from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Union


# TODO(#1041): Use typing.NamedTuple once we require Python 3.
class Platform(namedtuple("Platform", ["platform", "impl", "version", "abi"])):
    """Represents a target platform and it's extended interpreter compatibility tags (e.g.
    implementation, version and ABI)."""

    class InvalidPlatformError(Exception):
        """Indicates an invalid platform string."""

    SEP = "-"

    @classmethod
    def create(cls, platform):
        # type: (Union[str, Platform]) -> Platform
        if isinstance(platform, Platform):
            return platform

        platform = platform.lower()
        try:
            platform, impl, version, abi = platform.rsplit(cls.SEP, 3)
            return cls(platform, impl, version, abi)
        except ValueError:
            raise cls.InvalidPlatformError(
                dedent(
                    """\
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
                    
                    Some other canonical platform string examples:
                    + OSX CPython: macosx-10.13-x86_64-cp-36-cp36m
                    + Linux PyPy: linux-x86_64-pp-273-pypy_73.
                    
                    These fields stem from wheel name conventions as outlined in
                    https://www.python.org/dev/peps/pep-0427#file-name-convention and influenced by
                    https://www.python.org/dev/peps/pep-0425.
                    """.format(
                        platform
                    )
                )
            )

    @staticmethod
    def _maybe_prefix_abi(impl, version, abi):
        # type: (str, str, str) -> str
        if impl != "cp":
            return abi
        # N.B. This permits CPython users to pass in simpler extended platform
        # strings like `linux-x86_64-cp-27-mu` vs e.g. `linux-x86_64-cp-27-cp27mu`.
        impl_ver = "".join((impl, version))
        return abi if abi.startswith(impl_ver) else "".join((impl_ver, abi))

    @classmethod
    def from_tags(cls, platform, python, abi):
        # type: (str, str, str) -> Platform
        """Creates a platform corresponding to wheel compatibility tags.

        See: https://www.python.org/dev/peps/pep-0425/#details
        """
        impl, version = python[:2], python[2:]
        return cls(platform=platform, impl=impl, version=version, abi=abi)

    def __new__(cls, platform, impl, version, abi):
        if not all((platform, impl, version, abi)):
            raise cls.InvalidPlatformError(
                "Platform specifiers cannot have blank fields. Given platform={platform!r}, "
                "impl={impl!r}, version={version!r}, abi={abi!r}".format(
                    platform=platform, impl=impl, version=version, abi=abi
                )
            )
        platform = platform.replace("-", "_").replace(".", "_")
        abi = cls._maybe_prefix_abi(impl, version, abi)
        return super(Platform, cls).__new__(cls, platform, impl, version, abi)

    @property
    def platform(self):
        # type: () -> str
        return cast(str, super(Platform, self).platform)

    @property
    def impl(self):
        # type: () -> str
        return cast(str, super(Platform, self).impl)

    @property
    def version(self):
        # type: () -> str
        return cast(str, super(Platform, self).version)

    @property
    def abi(self):
        # type: () -> str
        return cast(str, super(Platform, self).abi)

    def __str__(self):
        # type: () -> str
        return cast(str, self.SEP.join(self))
