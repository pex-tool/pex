# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from collections import OrderedDict

from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import (
    InterpreterConstraints,
    UnsatisfiableInterpreterConstraintsError,
)
from pex.orderedset import OrderedSet
from pex.pex_bootstrapper import iter_compatible_interpreters, normalize_path
from pex.platforms import Platform
from pex.targets import CompletePlatform, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import FrozenSet, Iterator, Optional, Set, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class InterpreterConfiguration(object):
    _python_path = attr.ib(default=None)  # type: Optional[Tuple[str, ...]]
    pythons = attr.ib(default=())  # type: Tuple[str, ...]
    interpreter_constraints = attr.ib(
        default=InterpreterConstraints()
    )  # type: InterpreterConstraints

    @property
    def python_path(self):
        # type: () -> Optional[Tuple[str, ...]]
        # TODO(#1075): stop looking at PEX_PYTHON_PATH and solely consult the `--python-path` flag.
        return self._python_path or ENV.PEX_PYTHON_PATH

    def iter_interpreters(self):
        # type: () -> Iterator[PythonInterpreter]

        if self.pythons:
            with TRACER.timed("Resolving interpreters", V=2):

                def to_python_interpreter(full_path_or_basename):
                    if os.path.isfile(full_path_or_basename):
                        return PythonInterpreter.from_binary(full_path_or_basename)
                    else:
                        interpreter = PythonInterpreter.from_env(
                            full_path_or_basename, paths=normalize_path(self.python_path)
                        )
                        if interpreter is None:
                            raise InterpreterNotFound(
                                "Failed to find interpreter: {}".format(full_path_or_basename)
                            )
                        return interpreter

                for python in self.pythons:
                    yield to_python_interpreter(python)

        if self.interpreter_constraints:
            with TRACER.timed("Resolving interpreters", V=2):
                try:
                    for interp in iter_compatible_interpreters(
                        path=self.python_path,
                        interpreter_constraints=self.interpreter_constraints,
                    ):
                        yield interp
                except UnsatisfiableInterpreterConstraintsError as e:
                    raise InterpreterConstraintsNotSatisfied(
                        e.create_message("Could not find a compatible interpreter.")
                    )

    def resolve_interpreters(self):
        # type: () -> OrderedSet[PythonInterpreter]
        """Resolves the interpreters satisfying the interpreter configuration.

        :raise: :class:`InterpreterNotFound` specific --python interpreters were requested but could
            not be found.
        :raise: :class:`InterpreterConstraintsNotSatisfied` if --interpreter-constraint were
            specified but no conforming interpreters could be found.
        """
        return OrderedSet(self.iter_interpreters())


class TargetConfigurationError(Exception):
    """Indicates a problem configuring resolve targets."""


class InterpreterNotFound(TargetConfigurationError):
    """Indicates an explicitly requested interpreter could not be found."""


class InterpreterConstraintsNotSatisfied(TargetConfigurationError):
    """Indicates no interpreter meeting the requested constraints could be found."""


def _interpreter_compatible_platforms(
    all_platforms,  # type: OrderedDict[Optional[Platform], Optional[CompletePlatform]]
    candidate_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> FrozenSet[Platform]
    resolved_platforms = candidate_interpreter.supported_platforms.intersection(
        all_platforms
    )  # type: FrozenSet[Platform]
    incompatible_platforms = set()  # type: Set[Platform]

    for resolved_platform in resolved_platforms:
        requested_complete = all_platforms[resolved_platform]
        if requested_complete is not None:
            # if there was an explicit complete platform specified, only use the local interpreter
            # when the interpreter's tags are a subset of the complete platform's: tags supported by
            # the interpreter but not the complete platform may result in incompatible wheels being
            # chosen, if the interpreter was used directly
            candidate_complete = CompletePlatform.from_interpreter(candidate_interpreter)
            requested_tags = set(requested_complete.supported_tags)
            missing_tags = OrderedSet(
                t for t in candidate_complete.supported_tags if t not in requested_tags
            )
            if missing_tags:
                TRACER.log(
                    "Rejected resolution of {} for platform {} due to supporting {} extra tags".format(
                        candidate_interpreter,
                        resolved_platform,
                        len(missing_tags),
                    ),
                    V=3,
                )
                TRACER.log(
                    "Extra tags supported by {} for platform {} but not supported by specified complete platform: {}".format(
                        candidate_interpreter,
                        resolved_platform,
                        ", ".join(map(str, missing_tags)),
                    ),
                    V=9,
                )
                # keep iterating to give information about each of the relevant platforms
                incompatible_platforms.add(resolved_platform)
                continue

        TRACER.log(
            "Provisionally accepted resolution of {} for platform {} due to matching {}".format(
                candidate_interpreter,
                resolved_platform,
                "tags"
                if requested_complete is not None
                else "platform (no complete platform and thus no tags to check)",
            ),
            V=3,
        )

    if incompatible_platforms:
        TRACER.log(
            "Rejected interpreter {} due to being incompatible with {}: {}".format(
                candidate_interpreter,
                "a platform" if len(incompatible_platforms) == 1 else "some platforms",
                ", ".join(sorted(map(str, incompatible_platforms))),
            )
        )
        return frozenset()

    return resolved_platforms


@attr.s(frozen=True)
class TargetConfiguration(object):
    interpreter_configuration = attr.ib(
        default=InterpreterConfiguration()
    )  # type: InterpreterConfiguration

    @property
    def pythons(self):
        # type: () -> Tuple[str, ...]
        return self.interpreter_configuration.pythons

    @property
    def interpreter_constraints(self):
        # type: () -> InterpreterConstraints
        return self.interpreter_configuration.interpreter_constraints

    complete_platforms = attr.ib(default=())  # type: Tuple[CompletePlatform, ...]
    platforms = attr.ib(default=())  # type: Tuple[Optional[Platform], ...]
    assume_manylinux = attr.ib(default="manylinux2014")  # type: Optional[str]
    resolve_local_platforms = attr.ib(default=False)  # type: bool

    def resolve_targets(self):
        # type: () -> Targets
        """Resolves the targets satisfying the target configuration.

        :raise: :class:`InterpreterNotFound` specific --python interpreters were requested but could
            not be found.
        :raise: :class:`InterpreterConstraintsNotSatisfied` if --interpreter-constraint were
            specified but no conforming interpreters could be found.
        """
        interpreters = self.interpreter_configuration.resolve_interpreters()

        all_platforms = (
            OrderedDict()
        )  # type: OrderedDict[Optional[Platform], Optional[CompletePlatform]]
        all_platforms.update(
            (complete_platform.platform, complete_platform)
            for complete_platform in self.complete_platforms
        )
        all_platforms.update((platform, None) for platform in self.platforms)
        if all_platforms and self.resolve_local_platforms:
            with TRACER.timed(
                "Searching for local interpreters matching {}".format(
                    ", ".join(map(str, all_platforms))
                )
            ):
                candidate_interpreters = OrderedSet(
                    iter_compatible_interpreters(path=self.interpreter_configuration.python_path)
                )  # type: OrderedSet[PythonInterpreter]
                candidate_interpreters.add(PythonInterpreter.get())
                for candidate_interpreter in candidate_interpreters:
                    resolved_platforms = _interpreter_compatible_platforms(
                        all_platforms, candidate_interpreter
                    )
                    if resolved_platforms:
                        for resolved_platform in resolved_platforms:
                            TRACER.log(
                                "Resolved {} for platform {}".format(
                                    candidate_interpreter, resolved_platform
                                )
                            )
                            all_platforms.pop(resolved_platform)
                        interpreters.add(candidate_interpreter)
            if all_platforms:
                TRACER.log(
                    "Could not resolve a local interpreter for {}, will resolve only binary "
                    "distributions for {}.".format(
                        ", ".join(map(str, all_platforms)),
                        "this platform" if len(all_platforms) == 1 else "these platforms",
                    )
                )

        complete_platforms = []
        platforms = []
        for platform, complete_platform in all_platforms.items():
            if complete_platform:
                complete_platforms.append(complete_platform)
            else:
                platforms.append(platform)

        return Targets(
            interpreters=tuple(interpreters),
            complete_platforms=tuple(complete_platforms),
            platforms=tuple(platforms),
            assume_manylinux=self.assume_manylinux,
        )
