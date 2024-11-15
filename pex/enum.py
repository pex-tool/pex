# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import sys
import weakref
from collections import defaultdict
from functools import total_ordering

from _weakref import ReferenceType

from pex.exceptions import production_assert
from pex.typing import TYPE_CHECKING, Generic, cast

if TYPE_CHECKING:
    from typing import Any, DefaultDict, Iterator, List, Optional, Tuple, Type, TypeVar

    _V = TypeVar("_V", bound="Enum.Value")


def _get_or_create(
    module,  # type: str
    enum_type,  # type: str
    enum_value_type,  # type: str
    enum_value_value,  # type: str
):
    # type: (...) -> Enum.Value
    enum_class = getattr(sys.modules[module], enum_type)
    enum_value_class = getattr(enum_class, enum_value_type)
    return cast("Enum.Value", enum_value_class._get_or_create(enum_value_value))


class Enum(Generic["_V"]):
    @total_ordering
    class Value(object):
        _values_by_type = defaultdict(
            list
        )  # type: DefaultDict[Type[Enum.Value], List[ReferenceType[Enum.Value]]]

        @classmethod
        def _iter_values(cls):
            # type: () -> Iterator[Enum.Value]
            for ref in cls._values_by_type[cls]:
                value = ref()
                if value:
                    yield value

        @classmethod
        def _get_or_create(cls, value):
            # type: (str) -> Enum.Value
            for existing_value in cls._iter_values():
                if existing_value.value == value:
                    return existing_value
            return cls(value)

        def __reduce__(self):
            if sys.version_info[0] >= 3:
                return self._get_or_create, (self.value,)

            # N.B.: Python 2.7 does not handle pickling nested classes; so we go through some
            # hoops here and in `Enum.seal`.
            module = self.__module__
            enum_type = getattr(self, "_enum_type", None)
            production_assert(
                isinstance(enum_type, str),
                "The Enum subclass in the {module} module containing value {self} was not "
                "`seal`ed.",
                module=module,
                self=self,
            )
            return _get_or_create, (module, enum_type, type(self).__name__, self.value)

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

    @classmethod
    def seal(cls):
        if sys.version_info[0] >= 3:
            return

        # N.B.: Python 2.7 does not handle pickling nested classes; so we go through some
        # hoops here and in `Enum.Value.__reduce__`.

        enum_type_name, _, enum_value_type_name = cls.type_var.partition(".")
        if enum_value_type_name:
            production_assert(
                cls.__name__ == enum_type_name,
                "Expected Enum subclass {cls} to have a type parameter of the form `{name}.Value` "
                "where `Value` is a subclass of `Enum.Value`. Instead found: {type_var}",
                cls=cls,
                name=cls.__name__,
                type_var=cls.type_var,
            )
            enum_value_type = getattr(cls, enum_value_type_name, None)
        else:
            enum_value_type = getattr(sys.modules[cls.__module__], enum_type_name, None)

        production_assert(
            enum_type_name is not None,
            "Failed to find Enum.Value type {type_var} for Enum {cls} in module {module}",
            type_var=cls.type_var,
            cls=cls,
            module=cls.__module__,
        )
        production_assert(
            issubclass(enum_value_type, Enum.Value),
            "Expected Enum subclass {cls} to have a type parameter that is a subclass of "
            "`Enum.Value`. Instead found {type_var} was of type: {enum_value_type}",
            cls=cls,
            name=cls.__name__,
            type_var=cls.type_var,
            enum_value_type=enum_value_type,
        )
        setattr(enum_value_type, "_enum_type", cls.__name__)

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
