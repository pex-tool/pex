# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import Iterable, Type, TypeVar

    _V = TypeVar("_V", bound="Enum.Value")


class Enum(Generic["_V"]):
    class Value(object):
        def __init__(self, value):
            # type: (str) -> None
            self.value = value

        def __str__(self):
            # type: () -> str
            return str(self.value)

        def __repr__(self):
            # type: () -> str
            return repr(self.value)

    @classmethod
    def values(cls):
        # type: (Type[Enum[_V]]) -> Iterable[_V]
        raise NotImplementedError()

    @classmethod
    def for_value(
        cls,  # type: Type[Enum[_V]]
        value,  # type: str
    ):
        # type: (...) -> _V
        for v in cls.values():
            if v.value == value:
                return v
        raise ValueError(
            "{!r} of type {} must be one of {}".format(
                value, type(value), ", ".join(map(repr, cls.values()))
            )
        )
