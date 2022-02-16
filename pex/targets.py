# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Target(object):
    @classmethod
    def current(cls):
        # type: () -> Target
        return LocalInterpreter.create()

    id = attr.ib()  # type: str
    platform = attr.ib()  # type: Platform
    marker_environment = attr.ib()  # type: MarkerEnvironment

    def get_supported_tags(self):
        # type: () -> CompatibilityTags
        raise NotImplementedError()

    @property
    def is_foreign(self):
        # type: () -> bool
        """Does the distribution target represent a foreign platform.

        A foreign platform is one not matching the current interpreter.
        """
        return self.platform not in self.get_interpreter().supported_platforms

    def get_python_version_str(self):
        # type: () -> Optional[str]
        return self.marker_environment.python_full_version

    def get_interpreter(self):
        # type: () -> PythonInterpreter
        return PythonInterpreter.get()

    def requirement_applies(
        self,
        requirement,  # type: Requirement
        extras=None,  # type: Optional[Tuple[str, ...]]
    ):
        # type: (...) -> bool
        """Determines if the given requirement applies to this target.

        :param requirement: The requirement to evaluate.
        :param extras: Optional active extras.
        :returns: `True` if the requirement applies.
        """
        if requirement.marker is None:
            return True

        if not extras:
            # Provide an empty extra to safely evaluate the markers without matching any extra.
            extras = ("",)
        for extra in extras:
            environment = self.marker_environment.as_dict()
            environment["extra"] = extra
            if requirement.marker.evaluate(environment=environment):
                return True

        return False

    def __str__(self):
        # type: () -> str
        return str(self.platform.tag)


@attr.s(frozen=True)
class LocalInterpreter(Target):
    @classmethod
    def create(cls, interpreter=None):
        # type: (Optional[PythonInterpreter]) -> LocalInterpreter
        python_interpreter = interpreter or PythonInterpreter.get()
        return cls(
            id=python_interpreter.binary.replace(os.sep, ".").lstrip("."),
            platform=python_interpreter.platform,
            marker_environment=python_interpreter.identity.env_markers,
            interpreter=python_interpreter,
        )

    interpreter = attr.ib()  # type: PythonInterpreter

    @property
    def is_foreign(self):
        # type: () -> bool
        return False

    def get_python_version_str(self):
        # type: () -> str
        return self.interpreter.identity.version_str

    def get_interpreter(self):
        # type: () -> PythonInterpreter
        return self.interpreter

    def get_supported_tags(self):
        return self.interpreter.identity.supported_tags

    def __str__(self):
        # type: () -> str
        return self.interpreter.binary


@attr.s(frozen=True)
class AbbreviatedPlatform(Target):
    @classmethod
    def create(
        cls,
        platform,  # type: Platform
        manylinux=None,  # type: Optional[str]
    ):
        # type: (...) -> AbbreviatedPlatform
        return cls(
            id=str(platform),
            marker_environment=MarkerEnvironment.from_platform(platform),
            platform=platform,
            manylinux=manylinux,
        )

    manylinux = attr.ib()  # type: Optional[str]

    def get_supported_tags(self):
        # type: () -> CompatibilityTags
        return self.platform.supported_tags(manylinux=self.manylinux)


@attr.s(frozen=True)
class Targets(object):
    interpreters = attr.ib(default=())  # type: Tuple[PythonInterpreter, ...]
    platforms = attr.ib(default=())  # type: Tuple[Optional[Platform], ...]
    assume_manylinux = attr.ib(default=None)  # type: Optional[str]

    @property
    def interpreter(self):
        # type: () -> Optional[PythonInterpreter]
        if not self.interpreters:
            return None
        return PythonInterpreter.latest_release_of_min_compatible_version(self.interpreters)

    def unique_targets(self):
        # type: () -> OrderedSet[Target]

        def iter_targets():
            # type: () -> Iterator[Target]
            if not self.interpreters and not self.platforms:
                # No specified targets, so just build for the current interpreter (on the current
                # platform).
                yield Target.current()
                return

            for interpreter in self.interpreters:
                # Build for the specified local interpreters (on the current platform).
                yield LocalInterpreter.create(interpreter)

            for platform in self.platforms:
                if platform is None and not self.interpreters:
                    # Build for the current platform (None) only if not done already (ie: no
                    # intepreters were specified).
                    yield Target.current()
                elif platform is not None:
                    # Build for specific platforms.
                    yield AbbreviatedPlatform.create(platform, manylinux=self.assume_manylinux)

        return OrderedSet(iter_targets())
