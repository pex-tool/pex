# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
# OrderedSet recipe referenced in the Python standard library docs (bottom):
#     http://docs.python.org/library/collections.html
#
# Copied from recipe code found here: http://code.activestate.com/recipes/576694/ with small
# modifications
#

from __future__ import absolute_import

from collections import OrderedDict

from pex.compatibility import MutableSet
from pex.typing import TYPE_CHECKING, Generic, cast

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional


# N.B.: The item type is mixed in only at type checking time below due to class hierarchy metaclass
# conflicts. As such, we use Any here.
class _OrderedSet(MutableSet):
    def __init__(self, iterable=None):
        # type: (Optional[Iterable]) -> None
        self._data = OrderedDict()  # type: OrderedDict[Any, None]
        if iterable is not None:
            self.update(iterable)

    def __len__(self):
        # type: () -> int
        return len(self._data)

    def __contains__(self, key):
        # type: (Any) -> bool
        return key in self._data

    def add(self, key):
        # type: (Any) -> None
        self._data[key] = None

    def update(self, iterable):
        # type: (Iterable[Any]) -> None
        for key in iterable:
            self.add(key)

    def discard(self, key):
        # type: (Any) -> None
        self._data.pop(key, None)

    def __iter__(self):
        # type: () -> Iterator[Any]
        return iter(self._data)

    def __reversed__(self):
        # type: () -> Iterator[Any]
        return reversed(self._data)

    def pop(self, last=True):
        # type: (bool) -> Any
        if not self:
            raise KeyError("set is empty")
        key, _ = self._data.popitem(last=last)
        return key

    def __repr__(self):
        # type: () -> str
        if not self:
            return "{}()".format(
                self.__class__.__name__,
            )
        return "{}({!r})".format(self.__class__.__name__, list(self))

    def __eq__(self, other):
        # type: (Any) -> bool
        if type(other) != type(self):
            return NotImplemented
        # TODO(John Sirois): Type __eq__ as returning Union[bool, NotImplemented] when MyPy fixes:
        #  https://github.com/python/mypy/issues/4791
        return self._data == other._data  # type: ignore[no-any-return]


if TYPE_CHECKING:
    from typing import TypeVar

    _I = TypeVar("_I")

    # N.B.: We mix in Generic only in type checking mode since it uses a custom metaclass in
    # production which is inconsistent with _OrderedSet's base of MutableSet which has an ABCMeta
    # metaclass.
    class OrderedSet(_OrderedSet, Generic["_I"]):
        def __init__(self, iterable=None):
            # type: (Optional[Iterable[_I]]) -> None
            super(OrderedSet, self).__init__(iterable=iterable)

        def add(self, key):
            # type: (_I) -> None
            super(OrderedSet, self).add(key)

        def update(self, iterable):
            # type: (Iterable[_I]) -> None
            super(OrderedSet, self).update(iterable)

        def discard(self, key):
            # type: (_I) -> None
            super(OrderedSet, self).discard(key)

        def __iter__(self):
            # type: () -> Iterator[_I]
            return super(OrderedSet, self).__iter__()

        def __reversed__(self):
            # type: () -> Iterator[_I]
            return super(OrderedSet, self).__reversed__()

        def pop(self, last=True):
            # type: (bool) -> _I
            return cast("_I", super(OrderedSet, self).pop(last=last))

else:
    OrderedSet = _OrderedSet
