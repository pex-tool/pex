# Copyright 2019 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.dist_metadata import Distribution, Requirement
from pex.interpreter import PythonInterpreter, calculate_binary_name
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags, RankedTag
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform
from pex.result import Error
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.packaging.tags import Tag
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class RequiresPythonError(Exception):
    """Indicates the impossibility of evaluating Requires-Python metadata."""


@attr.s(frozen=True)
class WheelEvaluation(object):
    tags = attr.ib()  # type: Tuple[Tag, ...]
    best_match = attr.ib()  # type: Optional[RankedTag]
    requires_python = attr.ib()  # type: Optional[SpecifierSet]
    applies = attr.ib()  # type: bool

    def __bool__(self):
        # type: () -> bool
        return self.applies

    # N.B.: For Python 2.7.
    __nonzero__ = __bool__


@attr.s(frozen=True, repr=False)
class Target(object):
    id = attr.ib()  # type: str
    platform = attr.ib()  # type: Platform
    marker_environment = attr.ib()  # type: MarkerEnvironment

    def binary_name(self, version_components=2):
        # type: (int) -> str
        return calculate_binary_name(
            platform_python_implementation=self.marker_environment.platform_python_implementation,
            python_version=self.python_version[:version_components]
            if self.python_version and version_components > 0
            else None,
        )

    @property
    def python_version(self):
        # type: () -> Optional[Union[Tuple[int, int], Tuple[int, int, int]]]
        python_full_version = self.marker_environment.python_full_version
        if python_full_version:
            return cast("Tuple[int, int, int]", tuple(map(int, python_full_version.split(".")))[:3])
        python_version = self.marker_environment.python_version
        if python_version:
            return cast("Tuple[int, int]", tuple(map(int, python_version.split(".")))[:2])
        return None

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
        source,  # type: Any
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
        extras=(),  # type: Iterable[str]
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

    def wheel_applies(self, wheel):
        # type: (Distribution) -> WheelEvaluation
        wheel_tags = CompatibilityTags.from_wheel(wheel.location)
        ranked_tag = self.supported_tags.best_match(wheel_tags)
        return WheelEvaluation(
            tags=tuple(wheel_tags),
            best_match=ranked_tag,
            requires_python=wheel.metadata.requires_python,
            applies=(
                ranked_tag is not None
                and (
                    not wheel.metadata.requires_python
                    or self.requires_python_applies(
                        wheel.metadata.requires_python, source=wheel.location
                    )
                )
            ),
        )

    def __str__(self):
        # type: () -> str
        return str(self.platform.tag)

    def render_description(self):
        raise NotImplementedError()

    def __repr__(self):
        # type: () -> str
        return "{clazz}({self!r})".format(clazz=type(self).__name__, self=str(self))


@attr.s(frozen=True, repr=False)
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

    def binary_name(self, version_components=2):
        # type: (int) -> str
        return self.interpreter.identity.binary_name(version_components=version_components)

    @property
    def python_version(self):
        # type: () -> Tuple[int, int, int]
        return self.interpreter.identity.version[:3]

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


@attr.s(frozen=True, repr=False)
class AbbreviatedPlatform(Target):
    @classmethod
    def create(cls, platform):
        # type: (Platform) -> AbbreviatedPlatform
        return cls(
            id=str(platform.tag),
            marker_environment=MarkerEnvironment.from_platform(platform),
            platform=platform,
        )

    @property
    def supported_tags(self):
        # type: () -> CompatibilityTags
        return self.platform.supported_tags

    def render_description(self):
        return "abbreviated platform {platform}".format(platform=self.platform.tag)


def current():
    # type: () -> LocalInterpreter
    return LocalInterpreter.create()


@attr.s(frozen=True, repr=False)
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

        platform = Platform.from_tags(supported_tags)
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
    @classmethod
    def from_target(cls, target):
        # type: (Target) -> Targets
        if isinstance(target, AbbreviatedPlatform):
            return cls(platforms=(target.platform,))
        elif isinstance(target, CompletePlatform):
            return cls(complete_platforms=(target,))
        else:
            return cls(interpreters=(target.get_interpreter(),))

    interpreters = attr.ib(default=())  # type: Tuple[PythonInterpreter, ...]
    complete_platforms = attr.ib(default=())  # type: Tuple[CompletePlatform, ...]
    platforms = attr.ib(default=())  # type: Tuple[Optional[Platform], ...]

    @property
    def interpreter(self):
        # type: () -> Optional[PythonInterpreter]
        if not self.interpreters:
            return None
        return PythonInterpreter.latest_release_of_min_compatible_version(self.interpreters)

    def unique_targets(self, only_explicit=False):
        # type: (bool) -> OrderedSet[Target]

        def iter_targets():
            # type: () -> Iterator[Target]
            if (
                not only_explicit
                and not self.interpreters
                and not self.platforms
                and not self.complete_platforms
            ):
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
                    yield AbbreviatedPlatform.create(platform)

            for complete_platform in self.complete_platforms:
                yield complete_platform

        return OrderedSet(iter_targets())

    def require_unique_target(self, purpose):
        # type: (str) -> Union[Target, Error]
        resolved_targets = self.unique_targets()
        if len(resolved_targets) != 1:
            return Error(
                "A single target is required for {purpose}.\n"
                "There were {count} targets selected:\n"
                "{targets}".format(
                    purpose=purpose,
                    count=len(resolved_targets),
                    targets="\n".join(
                        "{index}. {target}".format(index=index, target=target)
                        for index, target in enumerate(resolved_targets, start=1)
                    ),
                )
            )
        return cast(Target, next(iter(resolved_targets)))

    def require_at_most_one_target(self, purpose):
        # type: (str) -> Union[Optional[Target], Error]
        resolved_targets = self.unique_targets(only_explicit=False)
        if len(resolved_targets) > 1:
            return Error(
                "At most a single target is required for {purpose}.\n"
                "There were {count} targets selected:\n"
                "{targets}".format(
                    purpose=purpose,
                    count=len(resolved_targets),
                    targets="\n".join(
                        "{index}. {target}".format(index=index, target=target)
                        for index, target in enumerate(resolved_targets, start=1)
                    ),
                )
            )
        try:
            return cast(Target, next(iter(resolved_targets)))
        except StopIteration:
            return None

    def compatible_shebang(self):
        # type: () -> Optional[str]
        pythons = {
            (target.platform.impl, target.platform.version_info[:2])
            for target in self.unique_targets()
        }
        if len(pythons) == 1:
            impl, version = pythons.pop()
            return "#!/usr/bin/env {python}{version}".format(
                python="pypy" if impl == "pp" else "python", version=".".join(map(str, version))
            )
        return None
