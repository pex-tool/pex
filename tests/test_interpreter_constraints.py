# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import itertools
import sys
from textwrap import dedent

import pytest

from pex import interpreter_constraints
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import (
    COMPATIBLE_PYTHON_VERSIONS,
    InterpreterConstraint,
    InterpreterConstraints,
    Lifecycle,
    UnsatisfiableError,
)
from pex.pex_warnings import PEXWarning
from pex.typing import TYPE_CHECKING
from testing import PY38, ensure_python_interpreter

if TYPE_CHECKING:
    from typing import List, Tuple


def test_parse():
    py38 = PythonInterpreter.from_binary(ensure_python_interpreter(PY38))

    assert py38 in InterpreterConstraint.parse("==3.8.*")
    assert py38 in InterpreterConstraint.parse("CPython==3.8.*")
    assert py38 in InterpreterConstraint.parse("==3.8.*", default_interpreter="CPython")
    assert py38 not in InterpreterConstraint.parse("==3.8.*", default_interpreter="PyPy")
    assert py38 not in InterpreterConstraint.parse("PyPy==3.8.*")

    with pytest.raises(
        UnsatisfiableError, match="The interpreter constraint ==3.8.*,==3.9.* is unsatisfiable."
    ):
        InterpreterConstraint.parse("==3.8.*,==3.9.*")

    with pytest.raises(
        UnsatisfiableError, match="The interpreter constraint ==3.8.*,==3.9.* is unsatisfiable."
    ):
        InterpreterConstraints.parse("==3.8.*,==3.9.*")

    with pytest.raises(
        UnsatisfiableError,
        match=dedent(
            """\
            Given interpreter constraints are unsatisfiable:
            ==3.8.*,==3.9.*
            ==3.9.*,<3.9
            """
        ).strip(),
    ):
        InterpreterConstraints.parse("==3.8.*,==3.9.*", "==3.9.*,<3.9")

    with pytest.warns(
        PEXWarning,
        match=dedent(
            """\
            Only 2 interpreter constraints are valid amongst: CPython==3.10.*,==3.11.* or CPython==3.10.*,==3.12.* or CPython==3.11.* or CPython==3.11.*,==3.12.* or CPython==3.11.*,==3.9.* or CPython==3.12.* or CPython==3.12.*,==3.9.*.
            Given interpreter constraints are unsatisfiable:
            CPython==3.10.*,==3.11.*
            CPython==3.10.*,==3.12.*
            CPython==3.11.*,==3.12.*
            CPython==3.11.*,==3.9.*
            CPython==3.12.*,==3.9.*
            Continuing using only CPython==3.11.* or CPython==3.12.*
            """
        ).strip(),
    ):
        InterpreterConstraints.parse(
            "CPython==3.10.*,==3.11.*",
            "CPython==3.10.*,==3.12.*",
            "CPython==3.11.*",
            "CPython==3.11.*,==3.12.*",
            "CPython==3.11.*,==3.9.*",
            "CPython==3.12.*",
            "CPython==3.12.*,==3.9.*",
        )


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


def test_iter_compatible_versions_non_eol():
    # type: () -> None

    oldest_python_version = COMPATIBLE_PYTHON_VERSIONS[0]
    assert Lifecycle.EOL == oldest_python_version.lifecycle

    newest_python_version = COMPATIBLE_PYTHON_VERSIONS[-1]
    assert Lifecycle.EOL != newest_python_version.lifecycle

    max_patch = oldest_python_version.patch + newest_python_version.patch + 1

    assert list(
        itertools.chain(
            [
                (oldest_python_version.major, oldest_python_version.minor, patch)
                for patch in range(oldest_python_version.patch + 1)
            ],
            [
                (newest_python_version.major, newest_python_version.minor, patch)
                for patch in range(max_patch + 1)
            ],
        )
    ) == list(
        interpreter_constraints.iter_compatible_versions(
            [
                "=={major}.{minor}.*".format(major=python_version.major, minor=python_version.minor)
                for python_version in (oldest_python_version, newest_python_version)
            ],
            max_patch=max_patch,
        )
    ), (
        "Expected the oldest python version to always be EOL and thus iterate its versions exactly "
        "and the newest python version to be non-EOL and iterate its versions past its patch all "
        "the way to the max patch."
    )
