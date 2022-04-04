# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import weakref
from collections import defaultdict
from functools import total_ordering

from _weakref import ReferenceType

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

        def __hash__(self):
            # type: () -> int
            return hash(self.value)

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


def qualified_name(item):
    # type: (Any) -> str
    """Attempt to produce the fully qualified name for an item.

    If the item is a type, method, property or function, its fully qualified name is returned as
    best as can be determined. Otherwise, the fully qualified name of the type of the given item is
    returned.

    :param item: The item to identify.
    :return: The fully qualified name of the given item.
    """
    if isinstance(item, property):
        item = item.fget
    if not hasattr(item, "__name__"):
        item = type(item)
    return "{module}.{type}".format(
        module=getattr(item, "__module__", "<unknown module>"),
        # There is no __qualname__ in Python 2.7; so we do the best we can.
        type=getattr(item, "__qualname__", item.__name__),
    )
