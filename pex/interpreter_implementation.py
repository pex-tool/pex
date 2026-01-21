# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import FrozenSet, List, Optional, Tuple


class _InterpreterImplementationValue(Enum.Value):
    def __init__(
        self,
        value,  # type: str
        abbr,  # type: str
        binary_name,  # type: str
        alias=None,  # type: Optional[str]
        free_threaded=None,  # type: Optional[bool]
        initial_version=None,  # type: Optional[Tuple[int, ...]]
    ):
        # type: (...) -> None
        super(_InterpreterImplementationValue, self).__init__(value)
        self.abbr = abbr
        self.binary_name = binary_name
        self.alias = alias
        self.free_threaded = free_threaded
        self._initial_version = initial_version

    def applies(self, version):
        # type: (Tuple[int, ...]) -> bool
        return self._initial_version is None or version >= self._initial_version

    def calculate_binary_name(self, version=None):
        # type: (Optional[Tuple[int, ...]]) -> str
        if not version:
            return self.binary_name
        return "{name}{version}{abiflags}".format(
            name=self.binary_name,
            version=".".join(map(str, version)),
            abiflags="t" if self.free_threaded and self.applies(version) else "",
        )


class InterpreterImplementation(Enum["InterpreterImplementation.Value"]):
    class Value(_InterpreterImplementationValue):
        def includes(self, implementation):
            # type: (InterpreterImplementation.Value) -> bool
            if self is implementation:
                return True
            if self is InterpreterImplementation.CPYTHON and implementation in (
                InterpreterImplementation.CPYTHON_FREE_THREADED,
                InterpreterImplementation.CPYTHON_GIL,
            ):
                return True
            return False

    @classmethod
    def covering_sets(cls):
        # type: () -> Tuple[FrozenSet[InterpreterImplementation.Value], ...]
        return frozenset((cls.CPYTHON, cls.PYPY)), frozenset(
            (cls.CPYTHON_FREE_THREADED, cls.CPYTHON_GIL, cls.PYPY)
        )

    @classmethod
    def for_value(cls, value):
        # type: (str) -> InterpreterImplementation.Value
        for v in cls.values():
            if v.value == value:
                return v
            if v.alias and v.alias == value:
                return v

        choices = []  # type: List[str]
        for v in cls.values():
            choices.append(v.value)
            if v.alias:
                choices.append(v.alias)
        raise ValueError(
            "{value!r} must be one of {choices}".format(value=value, choices=", ".join(choices))
        )

    CPYTHON = Value("CPython", "cp", "python")
    CPYTHON_FREE_THREADED = Value(
        "CPython+t",
        "cp",
        "python",
        alias="CPython[free-threaded]",
        free_threaded=True,
        initial_version=(3, 13),
    )
    CPYTHON_GIL = Value("CPython-t", "cp", "python", alias="CPython[gil]", free_threaded=False)
    PYPY = Value("PyPy", "pp", "pypy")


InterpreterImplementation.seal()
