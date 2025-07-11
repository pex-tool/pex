# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex import atexit
from pex.atexit import AtExit, Once
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List


def test_reverse_order():
    # type: () -> None

    tasks = []  # type: List[str]
    atexit.register(tasks.append, "foo")
    atexit.register(tasks.append, "bar")
    atexit.register(tasks.append, "baz")

    atexit.perform_exit()
    assert ["baz", "bar", "foo"] == tasks


def test_idempotent():
    # type: () -> None

    at_exit = AtExit()

    tasks = []  # type: List[str]
    at_exit.register(tasks.append, "foo")
    at_exit.register(tasks.append, "bar")
    at_exit.register(tasks.append, "baz")

    at_exit.exit()
    at_exit.exit()
    assert ["baz", "bar", "foo"] == tasks


def test_once():
    # type: () -> None

    tasks = []  # type: List[int]
    once = Once(tasks.append, 42)

    once()
    once()
    once()
    assert [42] == tasks
