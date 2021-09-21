# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.distribution_target import DistributionTarget
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.platforms import Platform
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Iterable, Iterator, Optional, Tuple, Union
else:
    from pex.third_party import attr


def _convert_interpreters(interpreters):
    # type: (Optional[Iterable[PythonInterpreter]]) -> Tuple[PythonInterpreter, ...]
    return tuple(interpreters) if interpreters else ()


def _parsed_platform(platform):
    # type: (Union[str, Optional[Platform]]) -> Optional[Platform]
    return Platform.create(platform) if platform and platform != "current" else None


def convert_platforms(platforms):
    # type: (Optional[Iterable[Union[str, Optional[Platform]]]]) -> Tuple[Optional[Platform], ...]
    return tuple(_parsed_platform(platform) for platform in platforms or ()) if platforms else ()


@attr.s(frozen=True)
class TargetConfiguration(object):
    interpreters = attr.ib(
        default=(), converter=_convert_interpreters
    )  # type: Tuple[PythonInterpreter, ...]

    platforms = attr.ib(
        default=(), converter=convert_platforms
    )  # type: Tuple[Optional[Platform], ...]

    assume_manylinux = attr.ib(default="manylinux2014")  # type: Optional[str]

    @property
    def interpreter(self):
        # type: () -> Optional[PythonInterpreter]
        if not self.interpreters:
            return None
        return PythonInterpreter.latest_release_of_min_compatible_version(self.interpreters)

    def unique_targets(self):
        # type: () -> OrderedSet[DistributionTarget]
        def iter_targets():
            # type: () -> Iterator[DistributionTarget]
            if not self.interpreters and not self.platforms:
                # No specified targets, so just build for the current interpreter (on the current
                # platform).
                yield DistributionTarget.current()
                return

            for interpreter in self.interpreters:
                # Build for the specified local interpreters (on the current platform).
                yield DistributionTarget.for_interpreter(interpreter)

            for platform in self.platforms:
                if platform is None and not self.interpreters:
                    # Build for the current platform (None) only if not done already (ie: no
                    # intepreters were specified).
                    yield DistributionTarget.current()
                elif platform is not None:
                    # Build for specific platforms.
                    yield DistributionTarget.for_platform(platform, manylinux=self.assume_manylinux)

        return OrderedSet(iter_targets())
