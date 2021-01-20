# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.interpreter import PythonInterpreter
from pex.platforms import Platform
from pex.third_party.packaging import tags
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Optional, Tuple


class DistributionTarget(object):
    """Represents the target of a python distribution."""

    @classmethod
    def current(cls):
        # type: () -> DistributionTarget
        return cls()

    @classmethod
    def for_interpreter(cls, interpreter):
        # type: (PythonInterpreter) -> DistributionTarget
        return cls(interpreter=interpreter)

    @classmethod
    def for_platform(
        cls,
        platform,  # type: Platform
        manylinux=None,  # type: Optional[str]
    ):
        # type: (...) -> DistributionTarget
        return cls(platform=platform, manylinux=manylinux)

    def __init__(
        self,
        interpreter=None,  # type: Optional[PythonInterpreter]
        platform=None,  # type:Optional[Platform]
        manylinux=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        if interpreter and platform:
            raise ValueError(
                "A {class_name} can represent an interpreter or a platform but not both at the "
                "same time. Given interpreter {interpreter} and platform {platform}.".format(
                    class_name=self.__class__.__name__, interpreter=interpreter, platform=platform
                )
            )
        if manylinux and not platform:
            raise ValueError(
                "A value for manylinux only makes sense for platform distribution targets. Given "
                "manylinux={!r} but no platform.".format(manylinux)
            )
        self._interpreter = interpreter
        self._platform = platform
        self._manylinux = manylinux

    @property
    def is_foreign(self):
        # type: () -> bool
        if self._platform is None:
            return False
        return self._platform not in self.get_interpreter().supported_platforms

    def get_interpreter(self):
        # type: () -> PythonInterpreter
        return self._interpreter or PythonInterpreter.get()

    def get_python_version_str(self):
        # type: () -> Optional[str]
        if self._platform is not None:
            return None
        return self.get_interpreter().identity.version_str

    def get_platform(self):
        # type: () -> Tuple[Platform, Optional[str]]
        if self._platform is not None:
            return self._platform, self._manylinux
        return self.get_interpreter().platform, None

    def get_supported_tags(self):
        # type: () -> Tuple[tags.Tag, ...]
        if self._platform is not None:
            return self._platform.supported_tags(manylinux=self._manylinux)
        return self.get_interpreter().identity.supported_tags

    def requirement_applies(
        self,
        requirement,  # type: Requirement
        extras=None,  # type: Optional[Tuple[str, ...]]
    ):
        # type: (...) -> Optional[bool]
        """Determines if the given requirement applies to this distribution target.

        :param requirement: The requirement to evaluate.
        :param extras: Optional active extras.
        :returns: `True` if the requirement definitely applies, `False` if it definitely does not
                  and `None` if it might apply but not enough information is at hand to determine
                  if it does apply.
        """
        if requirement.marker is None:
            return True

        if self._platform is not None:
            # We can have no opinion for foreign platforms.
            return None

        if not extras:
            # Provide an empty extra to safely evaluate the markers without matching any extra.
            extras = ("",)
        for extra in extras:
            # N.B.: This nets us a copy of the markers so we're free to mutate.
            environment = self.get_interpreter().identity.env_markers
            environment["extra"] = extra
            if requirement.marker.evaluate(environment=environment):
                return True

        return False

    @property
    def id(self):
        # type: () -> str
        """A unique id for this distribution target suitable as a path name component."""
        if self._platform is None:
            interpreter = self.get_interpreter()
            return interpreter.binary.replace(os.sep, ".").lstrip(".")
        else:
            return str(self._platform)

    def __repr__(self):
        # type: () -> str
        if self._platform is None:
            return "{}(interpreter={!r})".format(self.__class__.__name__, self.get_interpreter())
        else:
            return "{}(platform={!r})".format(self.__class__.__name__, self._platform)

    def _tup(self):
        # type: () -> Tuple[Any, ...]
        return self._interpreter, self._platform

    def __eq__(self, other):
        # type: (Any) -> bool
        if type(other) is not DistributionTarget:
            return NotImplemented
        return self._tup() == cast(DistributionTarget, other)._tup()

    def __hash__(self):
        # type: () -> int
        return hash(self._tup())
