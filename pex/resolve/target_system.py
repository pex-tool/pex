# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum
from pex.interpreter_constraints import InterpreterConstraint
from pex.interpreter_implementation import InterpreterImplementation
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class TargetSystem(Enum["TargetSystem.Value"]):
    class Value(Enum.Value):
        pass

    LINUX = Value("linux")
    MAC = Value("mac")
    WINDOWS = Value("windows")


TargetSystem.seal()


@attr.s(frozen=True)
class UniversalTarget(object):
    implementation = attr.ib(default=None)  # type: Optional[InterpreterImplementation.Value]
    requires_python = attr.ib(default=())  # type: Tuple[SpecifierSet, ...]
    systems = attr.ib(default=())  # type: Tuple[TargetSystem.Value, ...]

    def iter_interpreter_constraints(self):
        # type: () -> Iterator[InterpreterConstraint]
        for specifier in self.requires_python:
            yield InterpreterConstraint(specifier=specifier, implementation=self.implementation)
