# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING, Generic, cast, overload

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional, Protocol, TypeVar, Union

    class Comparable(Protocol):
        def __lt__(self, other):
            # type: (Any) -> bool
            pass

    _CT = TypeVar("_CT", bound=Comparable)

    _T = TypeVar("_T", bound=Comparable)

    class Comparator(Protocol):
        def __call__(self, item):
            # type: (Any) -> Comparable
            pass


class SortedTuple(Generic["_CT"], tuple):
    @overload
    def __new__(cls):
        # type: () -> SortedTuple[Any]
        pass

    @overload
    def __new__(
        cls,
        iterable,  # type: Iterable[_CT]
        key=None,  # type: None
        reverse=False,  # type: bool
    ):
        # type: (...) -> SortedTuple[_CT]
        pass

    @overload
    def __new__(
        cls,
        iterable,  # type: Iterable[Any]
        key,  # type: Comparator
        reverse=False,  # type: bool
    ):
        # type: (...) -> SortedTuple[_CT]
        pass

    def __new__(
        cls,
        iterable=None,  # type: Union[None, Iterable[_CT], Iterable[Any]]
        key=None,  # type: Optional[Comparator]
        reverse=False,  # type: bool
    ):
        # type: (...) -> SortedTuple[_CT]
        return super(SortedTuple, cls).__new__(
            cls, sorted(iterable, key=key, reverse=reverse) if iterable else ()
        )

    @overload
    def __getitem__(self, index):
        # type: (int) -> _CT
        pass

    @overload
    def __getitem__(self, slice_spec):
        # type: (slice) -> SortedTuple[_CT]
        pass

    def __getitem__(self, item):
        # type: (Union[int, slice]) -> Union[_CT, SortedTuple[_CT]]
        return cast("Union[_CT, SortedTuple[_CT]]", tuple.__getitem__(self, item))

    def __iter__(self):
        # type: () -> Iterator[_CT]
        return tuple.__iter__(self)
