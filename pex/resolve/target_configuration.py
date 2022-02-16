# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from collections import OrderedDict

from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import UnsatisfiableInterpreterConstraintsError
from pex.orderedset import OrderedSet
from pex.pex_bootstrapper import iter_compatible_interpreters, parse_path
from pex.platforms import Platform
from pex.targets import CompletePlatform, Targets
from pex.third_party.pkg_resources import Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class InterpreterConfiguration(object):
    _python_path = attr.ib(default=None)  # type: Optional[str]
    pythons = attr.ib(default=())  # type: Tuple[str, ...]
    interpreter_constraints = attr.ib(default=())  # type: Tuple[Requirement, ...]

    @property
    def python_path(self):
        # type: () -> Optional[str]
        # TODO(#1075): stop looking at PEX_PYTHON_PATH and solely consult the `--python-path` flag.
        return self._python_path or ENV.PEX_PYTHON_PATH

    def resolve_interpreters(self):
        # type: () -> OrderedSet[PythonInterpreter]
        """Resolves the interpreters satisfying the interpreter configuration.

        :raise: :class:`InterpreterNotFound` specific --python interpreters were requested but could
            not be found.
        :raise: :class:`InterpreterConstraintsNotSatisfied` if --interpreter-constraint were
            specified but no conforming interpreters could be found.
        """
        interpreters = OrderedSet()  # type: OrderedSet[PythonInterpreter]

        if self.pythons:
            with TRACER.timed("Resolving interpreters", V=2):

                def to_python_interpreter(full_path_or_basename):
                    if os.path.isfile(full_path_or_basename):
                        return PythonInterpreter.from_binary(full_path_or_basename)
                    else:
                        interp = PythonInterpreter.from_env(
                            full_path_or_basename, paths=parse_path(self.python_path)
                        )
                        if interp is None:
                            raise InterpreterNotFound(
                                "Failed to find interpreter: {}".format(full_path_or_basename)
                            )
                        return interp

                interpreters.update(to_python_interpreter(interp) for interp in self.pythons)

        if self.interpreter_constraints:
            with TRACER.timed("Resolving interpreters", V=2):
                try:
                    interpreters.update(
                        iter_compatible_interpreters(
                            path=self.python_path,
                            interpreter_constraints=self.interpreter_constraints,
                        )
                    )
                except UnsatisfiableInterpreterConstraintsError as e:
                    raise InterpreterConstraintsNotSatisfied(
                        e.create_message("Could not find a compatible interpreter.")
                    )

        return interpreters


class TargetConfigurationError(Exception):
    """Indicates a problem configuring resolve targets."""


class InterpreterNotFound(TargetConfigurationError):
    """Indicates an explicitly requested interpreter could not be found."""


class InterpreterConstraintsNotSatisfied(TargetConfigurationError):
    """Indicates no interpreter meeting the requested constraints could be found."""


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
        # type: () -> Tuple[Requirement, ...]
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
        interpreters = OrderedSet(
            self.interpreter_configuration.resolve_interpreters()
        )  # type: OrderedSet[PythonInterpreter]

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
                    resolved_platforms = candidate_interpreter.supported_platforms.intersection(
                        all_platforms
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
