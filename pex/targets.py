# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class RequiresPythonError(Exception):
    """Indicates the impossibility of evaluating Requires-Python metadata."""


@attr.s(frozen=True)
class Target(object):
    id = attr.ib()  # type: str
    platform = attr.ib()  # type: Platform
    marker_environment = attr.ib()  # type: MarkerEnvironment

    @property
    def supported_tags(self):
        # type: () -> CompatibilityTags
        raise NotImplementedError()

    @property
    def is_foreign(self):
        # type: () -> bool
        """Does the distribution target represent a foreign platform.

        A foreign platform is one not matching the current interpreter.
        """
        return self.platform not in self.get_interpreter().supported_platforms

    @property
    def python_version_str(self):
        # type: () -> Optional[str]
        return self.marker_environment.python_full_version or self.marker_environment.python_version

    def get_interpreter(self):
        # type: () -> PythonInterpreter
        return PythonInterpreter.get()

    def requires_python_applies(
        self,
        requires_python,  # type: SpecifierSet
        source,  # type: Requirement
    ):
        # type: (...) -> bool
        """Determines if the given python requirement applies to this target.

        :param requires_python: The Python requirement to evaluate.
        :param source: The source of the Python requirement restriction.
        :returns: `True` if the Python requirement applies.
        """

        if not self.python_version_str:
            raise RequiresPythonError(
                "Encountered `Requires-Python: {requires_python}` when evaluating {source} "
                "for applicability but the Python version information needed to evaluate this "
                "requirement is not contained in the target being evaluated for: {target}".format(
                    requires_python=requires_python, source=source, target=self
                )
            )

        # N.B.: The `python_version_str` will be of the form `X.Y` for traditional
        # AbbreviatedPlatform targets with a PYVER of the form `XY`. The Requires-Python metadata
        # (see: https://www.python.org/dev/peps/pep-0345/#requires-python) can contain full versions
        # in its version specifier like `>=3.8.1`. PEP-440 (
        # https://www.python.org/dev/peps/pep-0440/#version-specifiers) specifier missing version
        # components are padded with zeros for all comparison operators besides `===` which can
        # silently lead to incorrect results. If the target platform has a PYVER of 38 we don't know
        # if that platform represents a final target of 3.8.0 or 3.8.1 or some other 3.8 version,
        # but Pip, which follows PEP-440, will evaluate `>=3.8.1` as false and exclude the
        # distribution from consideration.
        #
        # Since our evaluation of `requires_python_applies` (and `requirement_applies`) is always
        # upon _results_ of an underlying Pip resolve (when we resolve from a PEX repository or a
        # lock file), the damage is already done when the distribution has already been incorrectly
        # excluded as in the example above; so we will not have to evaluate it. The other case is
        # when the distribution was incorrectly included. It's this case we need to contend with.
        #
        # If we use the same logic as Pip for an abbreviated platform resolve against a PEX or
        # lockfile, we'll include too much in the resulting PEX or lockfile. However, when the
        # resulting PEX or lockfile gets used "for real" there will be a local interpreter involved
        # and the `Requires-Python` will be correctly evaluated leading to the distribution not
        # being activated. This result is correct at the expense of wasting the space needed to
        # carry along the distribution that was not activated.
        #
        # It turns out that by just passing "X.Y" to SpecifierSet.__contains__ does evaluate "X.Y"
        # as if it were "X.Y.0" when zero-padding is appropriate (since it implements PEP-440); so
        # we get the Pip emulating behavior described above.
        return self.python_version_str in requires_python

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

    def render_description(self):
        raise NotImplementedError()


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

    @property
    def python_version_str(self):
        # type: () -> str
        return self.interpreter.identity.version_str

    def get_interpreter(self):
        # type: () -> PythonInterpreter
        return self.interpreter

    @property
    def supported_tags(self):
        return self.interpreter.identity.supported_tags

    def __str__(self):
        # type: () -> str
        return self.interpreter.binary

    def render_description(self):
        return "{platform} interpreter at {path}".format(
            platform=self.interpreter.platform.tag, path=self.interpreter.binary
        )


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
            id=str(platform.tag),
            marker_environment=MarkerEnvironment.from_platform(platform),
            platform=platform,
            manylinux=manylinux,
        )

    manylinux = attr.ib()  # type: Optional[str]

    @property
    def supported_tags(self):
        # type: () -> CompatibilityTags
        return self.platform.supported_tags(manylinux=self.manylinux)

    def render_description(self):
        return "abbreviated platform {platform}".format(platform=self.platform.tag)


def current():
    # type: () -> LocalInterpreter
    return LocalInterpreter.create()


@attr.s(frozen=True)
class CompletePlatform(Target):
    @classmethod
    def from_interpreter(cls, interpreter):
        # type: (PythonInterpreter) -> CompletePlatform
        return cls.create(
            marker_environment=interpreter.identity.env_markers,
            supported_tags=interpreter.identity.supported_tags,
        )

    @classmethod
    def create(
        cls,
        marker_environment,  # type: MarkerEnvironment
        supported_tags,  # type: CompatibilityTags
    ):
        # type: (...) -> CompletePlatform

        platform = Platform.from_tag(supported_tags[0])
        return cls(
            id=str(platform.tag),
            marker_environment=marker_environment,
            platform=platform,
            supported_tags=supported_tags,
        )

    _supported_tags = attr.ib()  # type: CompatibilityTags

    @property
    def supported_tags(self):
        # type: () -> CompatibilityTags
        return self._supported_tags

    def render_description(self):
        return "complete platform {platform}".format(platform=self.platform.tag)


@attr.s(frozen=True)
class Targets(object):
    interpreters = attr.ib(default=())  # type: Tuple[PythonInterpreter, ...]
    complete_platforms = attr.ib(default=())  # type: Tuple[CompletePlatform, ...]
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
            if not self.interpreters and not self.platforms and not self.complete_platforms:
                # No specified targets, so just build for the current interpreter (on the current
                # platform).
                yield current()
                return

            for interpreter in self.interpreters:
                # Build for the specified local interpreters (on the current platform).
                yield LocalInterpreter.create(interpreter)

            for platform in self.platforms:
                if platform is None and not self.interpreters:
                    # Build for the current platform (None) only if not done already (ie: no
                    # interpreters were specified).
                    yield current()
                elif platform is not None:
                    # Build for specific platforms.
                    yield AbbreviatedPlatform.create(platform, manylinux=self.assume_manylinux)

            for complete_platform in self.complete_platforms:
                yield complete_platform

        return OrderedSet(iter_targets())
