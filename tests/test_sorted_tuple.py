# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.sorted_tuple import SortedTuple


def test_empty():
    # type: () -> None
    empty = SortedTuple()
    assert 0 == len(empty)
    assert [] == list(empty)


def test_non_empty():
    # type: () -> None
    non_empty = SortedTuple([1])
    assert [1] == list(non_empty)


def test_sorting():
    # type: () -> None
    sorted_tuple = SortedTuple([3, 1, 5, 1, 3, 2, 4, 0])
    assert [0, 1, 1, 2, 3, 3, 4, 5] == list(sorted_tuple)
