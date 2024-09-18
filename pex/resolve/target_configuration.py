# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

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
    from typing import FrozenSet, Iterator, Optional, Tuple

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
    requested_complete_platforms,  # type: OrderedSet[CompletePlatform]
    candidate_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> FrozenSet[CompletePlatform]
    compatible_complete_platforms = []
    for requested_complete in requested_complete_platforms:
        # if there was an explicit complete platform specified, only use the local interpreter
        # when the interpreter's tags are a subset of the complete platform's: tags supported by
        # the interpreter but not the complete platform may result in incompatible wheels being
        # chosen, if the interpreter was used directly
        interpreter_platform = CompletePlatform.from_interpreter(candidate_interpreter)
        missing_tags = set(interpreter_platform.supported_tags) - set(
            requested_complete.supported_tags
        )
        if missing_tags:
            TRACER.log(
                "Rejected candidate interpreter {} for complete platform {} since interpreter supports {} extra tags".format(
                    candidate_interpreter,
                    requested_complete.platform,
                    len(missing_tags),
                ),
                V=3,
            )
            TRACER.log(
                "Extra tags supported by {} but not supported by requested complete platform {}: {}".format(
                    candidate_interpreter,
                    requested_complete.platform,
                    ", ".join(map(str, missing_tags)),
                ),
                V=9,
            )
        else:
            TRACER.log(
                "Accepted resolution of {} for complete platform {}".format(
                    candidate_interpreter,
                    requested_complete,
                ),
                V=3,
            )
            compatible_complete_platforms.append(requested_complete)

    return frozenset(compatible_complete_platforms)


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

        requested_platforms = OrderedSet(self.platforms)  # type: OrderedSet[Optional[Platform]]
        requested_complete_platforms = OrderedSet(
            self.complete_platforms
        )  # type: OrderedSet[CompletePlatform]
        if (requested_platforms or requested_complete_platforms) and self.resolve_local_platforms:
            # If any platform or complete_platform matches a local interpreter, we remove that
            # platform or complete_platform from the requested_* set and instead use the
            # interpreter.

            platform_strs = list(map(str, requested_complete_platforms)) + list(
                map(str, requested_platforms)
            )
            with TRACER.timed(
                "Searching for local interpreters matching {}".format(", ".join(platform_strs))
            ):
                candidate_interpreters = OrderedSet(
                    iter_compatible_interpreters(path=self.interpreter_configuration.python_path)
                )  # type: OrderedSet[PythonInterpreter]
                candidate_interpreters.add(PythonInterpreter.get())
                for candidate_interpreter in candidate_interpreters:
                    resolved_platforms = candidate_interpreter.supported_platforms.intersection(
                        requested_platforms
                    )
                    if resolved_platforms:
                        for resolved_platform in resolved_platforms:
                            TRACER.log(
                                "Resolved {} for platform {}".format(
                                    candidate_interpreter, resolved_platform
                                )
                            )
                            requested_platforms.remove(resolved_platform)
                        interpreters.add(candidate_interpreter)

                    resolved_complete_platforms = _interpreter_compatible_platforms(
                        requested_complete_platforms, candidate_interpreter
                    )
                    if resolved_complete_platforms:
                        for resolved_complete_platform in resolved_complete_platforms:
                            TRACER.log(
                                "Resolved {} for complete platform {}".format(
                                    candidate_interpreter, resolved_complete_platform
                                )
                            )
                            requested_complete_platforms.remove(resolved_complete_platform)
                        interpreters.add(candidate_interpreter)

            if requested_platforms or requested_complete_platforms:
                platform_strs = list(map(str, requested_complete_platforms)) + list(
                    map(str, requested_platforms)
                )
                TRACER.log(
                    "Could not resolve a local interpreter for {}, will resolve only binary "
                    "distributions for {}.".format(
                        ", ".join(platform_strs),
                        "this platform" if len(platform_strs) == 1 else "these platforms",
                    )
                )

        return Targets(
            interpreters=tuple(interpreters),
            complete_platforms=tuple(requested_complete_platforms),
            platforms=tuple(requested_platforms),
        )
