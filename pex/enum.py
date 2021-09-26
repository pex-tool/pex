# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import weakref
from collections import defaultdict
from functools import total_ordering

from _weakref import ReferenceType

from pex.common import qualified_name
from pex.typing import TYPE_CHECKING, Generic, cast

if TYPE_CHECKING:
    from typing import Any, DefaultDict, List, Optional, Tuple, Type, TypeVar

    _V = TypeVar("_V", bound="Enum.Value")


class Enum(Generic["_V"]):
    @total_ordering
    class Value(object):
        _values_by_type = defaultdict(
            list
        )  # type: DefaultDict[Type[Enum.Value], List[ReferenceType[Enum.Value]]]

        @classmethod
        def _iter_values(cls):
            for ref in cls._values_by_type[cls]:
                value = ref()
                if value:
                    yield value

        def __init__(self, value):
            # type: (str) -> None
            values = Enum.Value._values_by_type[type(self)]
            self.value = value
            self.ordinal = len(values)
            values.append(weakref.ref(self))

        def __str__(self):
            # type: () -> str
            return str(self.value)

        def __repr__(self):
            # type: () -> str
            return repr(self.value)

        def __eq__(self, other):
            # type: (Any) -> bool
            return self is other

        @classmethod
        def _create_type_error(cls, other):
            # type: (Any) -> TypeError
            return TypeError(
                "Can only compare values of type {value_type} amongst themselves; given "
                "{other!r} of type {other_type}.".format(
                    value_type=qualified_name(cls),
                    other=other,
                    other_type=qualified_name(other),
                )
            )

        def __lt__(self, other):
            # type: (Any) -> bool
            if type(self) != type(other):
                raise self._create_type_error(other)
            return self.ordinal < cast(Enum.Value, other).ordinal

        def __le__(self, other):
            # type: (Any) -> bool
            if type(self) != type(other):
                raise self._create_type_error(other)
            return self is other or self < other

    _values = None  # type: Optional[Tuple[_V, ...]]

    @classmethod
    def values(cls):
        # type: (Type[Enum[_V]]) -> Tuple[_V, ...]
        if cls._values is None:
            cls._values = tuple(cls.Value._iter_values())
        return cls._values

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
