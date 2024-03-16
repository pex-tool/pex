# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING, Generic, overload

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional, Protocol, TypeVar, Union

    from typing_extensions import SupportsIndex

    _T = TypeVar("_T")

    class _Comparable(Protocol):
        def __lt__(self, other):
            # type: (Any) -> bool
            pass

    class _TComparator(Protocol):
        def __call__(self, item):
            # type: (_T) -> _Comparable
            pass


class SortedTuple(Generic["_T"], tuple):
    @overload
    def __new__(cls):
        # type: () -> SortedTuple[Any]
        pass

    @overload
    def __new__(
        cls,
        iterable,  # type: Iterable[_T]
        key=None,  # type: None
        reverse=False,  # type: bool
    ):
        # type: (...) -> SortedTuple[_T]
        pass

    @overload
    def __new__(
        cls,
        iterable,  # type: Iterable[_T]
        key,  # type: _TComparator
        reverse=False,  # type: bool
    ):
        # type: (...) -> SortedTuple[_T]
        pass

    def __new__(
        cls,
        iterable=(),  # type: Iterable[_T]
        key=None,  # type: Optional[_TComparator]
        reverse=False,  # type: bool
    ):
        # type: (...) -> SortedTuple[_T]
        return super(SortedTuple, cls).__new__(
            cls,
            # There appears to be no way to express that _T should be comparable if no key function
            # is passed, but otherwise should be comparable.
            sorted(iterable, key=key, reverse=reverse),  # type: ignore[arg-type, type-var]
        )

    @overload
    def __getitem__(self, index):
        # type: (SupportsIndex) -> _T
        pass

    @overload
    def __getitem__(self, slice_spec):
        # type: (slice) -> SortedTuple[_T]
        pass

    def __getitem__(self, item):
        # type: (Union[SupportsIndex, slice]) -> Union[_T, SortedTuple[_T]]

        # MyPy `--python-version 2.7` does not understand SupportsIndex and the bifurcated return
        # type does not appear to be expressible.
        return tuple.__getitem__(self, item)  # type: ignore[index, return-value]

    def __iter__(self):
        # type: () -> Iterator[_T]
        return tuple.__iter__(self)
