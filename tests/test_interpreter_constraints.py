# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import sys

from pex import interpreter_constraints
from pex.interpreter_constraints import Lifecycle, PythonVersion
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List, Tuple


def test_python_version_pad():
    # type: () -> None

    assert PythonVersion(Lifecycle.EOL, 1, 2, 3) == PythonVersion(Lifecycle.EOL, 1, 2, 3).pad(5)
    assert PythonVersion(Lifecycle.STABLE, 1, 2, 8) == PythonVersion(Lifecycle.STABLE, 1, 2, 3).pad(
        5
    )
    assert PythonVersion(Lifecycle.DEV, 3, 2, 6) == PythonVersion(Lifecycle.DEV, 3, 2, 1).pad(5)


def iter_compatible_versions(*requires_python):
    # type: (*str) -> List[Tuple[int, int, int]]
    return list(interpreter_constraints.iter_compatible_versions(list(requires_python)))


def test_iter_compatible_versions_none():
    # type: () -> None

    assert [] == iter_compatible_versions(">3.6,<3.6")
    assert [] == iter_compatible_versions("<2")
    assert [] == iter_compatible_versions(">4")
    assert [] == iter_compatible_versions("<2", ">4")


def test_iter_compatible_versions_basic():
    # type: () -> None

    # N.B.: 2.7.18 is EOL.
    assert [(2, 7, patch) for patch in range(19)] == iter_compatible_versions("==2.7.*")
    assert [(2, 7, patch) for patch in range(19)] == iter_compatible_versions("~=2.7")
    assert [(2, 7, patch) for patch in range(1, 19)] == iter_compatible_versions("==2.7.*,!=2.7.0")


def test_iter_compatible_versions_or():
    # type: () -> None

    # N.B.: 2.7.18 is EOL as is 3.5.10.
    assert (
        list(
            itertools.chain(
                [(2, 7, patch) for patch in range(19)],
                [(3, 5, patch) for patch in range(1, 11)],
            )
        )
        == iter_compatible_versions("==2.7.*", ">3.5,<3.6")
    )


def test_iter_compatible_versions_sorted():
    # type: () -> None

    # N.B.: 2.7.18 is EOL as is 3.5.10.
    assert list(
        itertools.chain(
            [(2, 7, patch) for patch in range(19)],
            [(3, 5, patch) for patch in range(1, 11)],
        )
    ) == iter_compatible_versions(
        ">3.5,<3.6",
        "==2.7.*",
    )


def test_iter_compatible_versions_current():
    # type: () -> None

    assert sys.version_info[:3] in set(
        iter_compatible_versions()
    ), "Expected every interpreter we test on to always be compatible"
