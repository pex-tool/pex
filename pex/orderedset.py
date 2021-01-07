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

from pex.compatibility import MutableSet
from pex.typing import TYPE_CHECKING, Generic, cast

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional, TypeVar

    _I = TypeVar("_I")


class OrderedSet(MutableSet, Generic["_I"]):
    KEY, PREV, NEXT = range(3)

    def __init__(self, iterable=None):
        # type: (Optional[Iterable[_I]]) -> None
        self.end = end = []  # type: ignore[var-annotated]
        end += [None, end, end]  # sentinel node for doubly linked list
        self.map = {}  # type: ignore[var-annotated] # key --> [key, prev, next]
        if iterable is not None:
            self.update(iterable)

    def __len__(self):
        return len(self.map)

    def __contains__(self, key):
        # type: (Any) -> bool
        return key in self.map

    def add(self, key):
        # type: (_I) -> None
        if key not in self.map:
            end = self.end
            curr = end[self.PREV]
            curr[self.NEXT] = end[self.PREV] = self.map[key] = [key, curr, end]

    def update(self, iterable):
        # type: (Iterable[_I]) -> None
        for key in iterable:
            self.add(key)

    def discard(self, key):
        # type: (Any) -> None
        if key in self.map:
            key, prev, next = self.map.pop(key)
            prev[self.NEXT] = next
            next[self.PREV] = prev

    def __iter__(self):
        # type: () -> Iterator[_I]
        end = self.end
        curr = end[self.NEXT]
        while curr is not end:
            yield curr[self.KEY]
            curr = curr[self.NEXT]

    def __reversed__(self):
        # type: () -> Iterator[_I]
        end = self.end
        curr = end[self.PREV]
        while curr is not end:
            yield curr[self.KEY]
            curr = curr[self.PREV]

    def pop(self, last=True):
        # type: (bool) -> _I
        if not self:
            raise KeyError("set is empty")
        key = next(reversed(self)) if last else next(iter(self))
        self.discard(key)
        return cast("_I", key)

    def __repr__(self):
        # type: () -> str
        return "{}({!r})".format(self.__class__.__name__, list(self))

    def __eq__(self, other):
        # type: (Any) -> bool
        if isinstance(other, OrderedSet):
            return len(self) == len(other) and list(self) == list(other)
        return set(self) == set(other)

    def __del__(self):
        # type: () -> None
        self.clear()  # remove circular references
