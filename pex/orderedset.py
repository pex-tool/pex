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
from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional, TypeVar, Union

    _I = TypeVar("_I")


class OrderedSet(MutableSet, Generic["_I"]):
    def __init__(self, iterable=None):
        # type: (Optional[Iterable[_I]]) -> None
        self._data = OrderedDict()  # type: OrderedDict[_I, None]
        if iterable is not None:
            self.update(iterable)

    def __len__(self):
        # type: () -> int
        return len(self._data)

    def __contains__(self, key):
        # type: (Any) -> bool
        return key in self._data

    def add(self, key):
        # type: (_I) -> None
        self._data[key] = None

    def update(self, iterable):
        # type: (Iterable[_I]) -> None
        for key in iterable:
            self.add(key)

    def discard(self, key):
        # type: (_I) -> None
        self._data.pop(key, None)

    def __iter__(self):
        # type: () -> Iterator[_I]
        return iter(self._data)

    def __reversed__(self):
        # type: () -> Iterator[_I]
        return reversed(self._data)

    def pop(self, last=True):
        # type: (bool) -> _I
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
        # type: (Any) -> Union[bool, NotImplemented]
        if type(other) != type(self):
            return NotImplemented
        return self._data == other._data
