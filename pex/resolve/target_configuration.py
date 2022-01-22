# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.distribution_target import DistributionTargets
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import UnsatisfiableInterpreterConstraintsError
from pex.orderedset import OrderedSet
from pex.pex_bootstrapper import iter_compatible_interpreters, parse_path
from pex.platforms import Platform
from pex.third_party.pkg_resources import Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Optional, Tuple
else:
    from pex.third_party import attr


class TargetConfigurationError(Exception):
    """Indicates a problem configuring resolve targets."""


class InterpreterNotFound(TargetConfigurationError):
    """Indicates an explicitly requested interpreter could not be found."""


class InterpreterConstraintsNotSatisfied(TargetConfigurationError):
    """Indicates no interpreter meeting the requested constraints could be found."""


@attr.s(frozen=True)
class TargetConfiguration(object):
    python_path = attr.ib(default=None)  # type: str
    pythons = attr.ib(default=())  # type: Tuple[str, ...]
    interpreter_constraints = attr.ib(default=())  # type: Tuple[Requirement, ...]

    platforms = attr.ib(default=())  # type: Tuple[Optional[Platform], ...]
    assume_manylinux = attr.ib(default="manylinux2014")  # type: Optional[str]
    resolve_local_platforms = attr.ib(default=False)  # type: bool

    def resolve_targets(self):
        # type: () -> DistributionTargets
        """Resolves the distribution targets satisfying the target configuration.

        :raise: :class:`InterpreterNotFound` specific --python interpreters were requested but could
            not be found.
        :raise: :class:`InterpreterConstraintsNotSatisfied` if --interpreter-constraint were
            specified but no conforming interpreters could be found.
        """

        # TODO(#1075): stop looking at PEX_PYTHON_PATH and solely consult the `--python-path` flag.
        # If None, this will result in using $PATH.
        pex_python_path = self.python_path or ENV.PEX_PYTHON_PATH

        interpreters = OrderedSet()  # type: OrderedSet[PythonInterpreter]
        platforms = OrderedSet(self.platforms)

        if self.pythons:
            with TRACER.timed("Resolving interpreters", V=2):

                def to_python_interpreter(full_path_or_basename):
                    if os.path.isfile(full_path_or_basename):
                        return PythonInterpreter.from_binary(full_path_or_basename)
                    else:
                        interp = PythonInterpreter.from_env(
                            full_path_or_basename, paths=parse_path(pex_python_path)
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
                            path=pex_python_path,
                            interpreter_constraints=self.interpreter_constraints,
                        )
                    )
                except UnsatisfiableInterpreterConstraintsError as e:
                    raise InterpreterConstraintsNotSatisfied(
                        e.create_message("Could not find a compatible interpreter.")
                    )

        if platforms and self.resolve_local_platforms:
            with TRACER.timed(
                "Searching for local interpreters matching {}".format(
                    ", ".join(map(str, platforms))
                )
            ):
                candidate_interpreters = OrderedSet(
                    iter_compatible_interpreters(path=pex_python_path)
                )
                candidate_interpreters.add(PythonInterpreter.get())
                for candidate_interpreter in candidate_interpreters:
                    resolved_platforms = candidate_interpreter.supported_platforms.intersection(
                        platforms
                    )
                    if resolved_platforms:
                        for resolved_platform in resolved_platforms:
                            TRACER.log(
                                "Resolved {} for platform {}".format(
                                    candidate_interpreter, resolved_platform
                                )
                            )
                            platforms.remove(resolved_platform)
                        interpreters.add(candidate_interpreter)
            if platforms:
                TRACER.log(
                    "Could not resolve a local interpreter for {}, will resolve only binary "
                    "distributions for {}.".format(
                        ", ".join(map(str, platforms)),
                        "this platform" if len(platforms) == 1 else "these platforms",
                    )
                )
        return DistributionTargets(
            interpreters=tuple(interpreters),
            platforms=tuple(platforms),
            assume_manylinux=self.assume_manylinux,
        )
