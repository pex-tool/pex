# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, Tuple


class _InterpreterImplementationValue(Enum.Value):
    def __init__(
        self,
        value,  # type: str
        abbr,  # type: str
        binary_name,  # type: str
    ):
        # type: (...) -> None
        super(_InterpreterImplementationValue, self).__init__(value)
        self.abbr = abbr
        self.binary_name = binary_name

    def calculate_binary_name(self, version=None):
        # type: (Optional[Tuple[int, ...]]) -> str
        if not version:
            return self.binary_name
        return "{name}{version}".format(name=self.binary_name, version=".".join(map(str, version)))


class InterpreterImplementation(Enum["InterpreterImplementation.Value"]):
    class Value(_InterpreterImplementationValue):
        pass

    CPYTHON = Value("CPython", "cp", "python")
    PYPY = Value("PyPy", "pp", "pypy")


InterpreterImplementation.seal()
