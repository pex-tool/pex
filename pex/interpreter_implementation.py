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
        free_threaded=None,  # type: Optional[bool]
    ):
        # type: (...) -> None
        super(_InterpreterImplementationValue, self).__init__(value)
        self.abbr = abbr
        self.binary_name = binary_name
        self.free_threaded = free_threaded

    def calculate_binary_name(self, version=None):
        # type: (Optional[Tuple[int, ...]]) -> str
        if not version:
            return self.binary_name
        return "{name}{version}{abiflags}".format(
            name=self.binary_name,
            version=".".join(map(str, version)),
            abiflags="t" if self.free_threaded else "",
        )


class InterpreterImplementation(Enum["InterpreterImplementation.Value"]):
    class Value(_InterpreterImplementationValue):
        pass

    CPYTHON = Value("CPython", "cp", "python")
    CPYTHON_FREE_THREADED = Value("CPython_t", "cp", "python", free_threaded=True)
    PYPY = Value("PyPy", "pp", "pypy")


InterpreterImplementation.seal()
