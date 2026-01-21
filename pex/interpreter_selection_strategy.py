# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Iterable, Tuple

    from pex.interpreter import PythonInterpreter


class InterpreterSelectionStrategyValue(Enum.Value):
    def __init__(
        self,
        value,  # type: str
        key_func,  # type: Callable[[PythonInterpreter], Tuple[int, int, int]]
    ):
        # type: (...) -> None
        super(InterpreterSelectionStrategyValue, self).__init__(value)
        self._key_func = key_func


class InterpreterSelectionStrategy(Enum["InterpreterSelectionStrategy.Value"]):
    class Value(InterpreterSelectionStrategyValue):
        def select(self, interpreters):
            # type: (Iterable[PythonInterpreter]) -> PythonInterpreter
            return min(interpreters, key=self._key_func)

    OLDEST = Value(
        "oldest",
        key_func=lambda interp: (interp.version[0], interp.version[1], -interp.version[2]),
    )
    NEWEST = Value(
        "newest",
        key_func=lambda interp: (-interp.version[0], -interp.version[1], -interp.version[2]),
    )


InterpreterSelectionStrategy.seal()
