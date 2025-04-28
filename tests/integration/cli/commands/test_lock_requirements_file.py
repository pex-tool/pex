# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import difflib
import filecmp
import os

import pytest

from pex.pip.version import PipVersion
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


def diff(
    file1,  # type: str
    file2,  # type: str
):
    # type: (...) -> str

    with open(file1) as fp1, open(file2) as fp2:
        return os.linesep.join(
            difflib.context_diff(fp1.readlines(), fp2.readlines(), fp1.name, fp2.name)
        )


def assert_locks_match(
    tmpdir,  # type: Tempdir
    *requirements  # type: str
):
    # type: (...) -> None

    lock1 = tmpdir.join("lock1.json")
    run_pex3(
        "lock",
        "create",
        "--pip-version",
        "latest-compatible",
        "-o",
        lock1,
        "--indent",
        "2",
        *requirements
    ).assert_success()

    requirements_file = tmpdir.join("requirements.txt")
    with open(requirements_file, "w") as fp:
        for requirement in requirements:
            print(requirement, file=fp)

    lock2 = tmpdir.join("lock2.json")
    run_pex3(
        "lock",
        "create",
        "--pip-version",
        "latest-compatible",
        "-o",
        lock2,
        "--indent",
        "2",
        "-r",
        requirements_file,
    ).assert_success()

    assert filecmp.cmp(lock1, lock2, shallow=False), diff(lock1, lock2)


def test_lock_by_name(tmpdir):
    # type: (Tempdir) -> None

    assert_locks_match(tmpdir, "cowsay<6")


def test_lock_vcs(tmpdir):
    # type: (Tempdir) -> None

    assert_locks_match(
        tmpdir, "ansicolors @ git+https://github.com/jonathaneunice/colors.git@c965f5b9"
    )


@pytest.mark.skipif(
    PipVersion.LATEST_COMPATIBLE is PipVersion.VENDORED,
    reason="Vendored Pip cannot handle modern pyproject.toml with heterogeneous arrays.",
)
def test_lock_local_project(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    assert_locks_match(tmpdir, pex_project_dir)


def test_lock_mixed(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    requirements = [
        "cowsay<6",
        "ansicolors @ git+https://github.com/jonathaneunice/colors.git@c965f5b9",
    ]
    # N.B.: Vendored Pip cannot handle modern pyproject.toml with heterogeneous arrays, which ours
    # uses.
    if PipVersion.LATEST_COMPATIBLE is not PipVersion.VENDORED:
        requirements.append(pex_project_dir)

    assert_locks_match(tmpdir, *requirements)
