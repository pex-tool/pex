# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from textwrap import dedent

from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Iterator, Union, Tuple


# TODO(#1041): Use typing.NamedTuple once we require Python 3.
class Platform(object):
    """Represents a target platform and it's extended interpreter compatibility tags (e.g.
    implementation, version and ABI)."""

    class InvalidPlatformError(Exception):
        """Indicates an invalid platform string."""

    SEP = "-"

    __slots__ = ("platform", "impl", "version", "abi")

    def __init__(self, platform, impl, version, abi):
        super(Platform, self).__init__()
        if not all((platform, impl, version, abi)):
            raise self.InvalidPlatformError(
                "Platform specifiers cannot have blank fields. Given platform={platform!r}, "
                "impl={impl!r}, version={version!r}, abi={abi!r}".format(
                    platform=platform, impl=impl, version=version, abi=abi
                )
            )
        self.platform = platform.replace("-", "_").replace(".", "_")
        self.impl = impl
        self.version = version
        self.abi = self._maybe_prefix_abi(impl, version, abi)

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

    def _tup(self):
        # type: () -> Tuple[str, str, str, str]
        return self.platform, self.impl, self.version, self.abi

    def __repr__(self):
        return "Platform(platform={}, impl={}, version={}, abi={})".format(*self._tup())

    def __str__(self):
        # type: () -> str
        return self.SEP.join(self._tup())

    def __eq__(self, other):
        # type: (Any) -> bool
        return cast(bool, self._tup() == other)

    def __hash__(self):
        # type: () -> int
        return hash(self._tup())

    def __iter__(self):
        # type: () -> Iterator[str]
        return iter(self._tup())
