# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys
from collections import deque

import pytest

from pex.compatibility import commonpath
from pex.pep_503 import ProjectName
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.pep_751 import Pylock
from pex.result import try_
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Deque, Iterable, Mapping


def assert_mkdocstrings_lock_cycle(lock):
    # type: (Mapping[ProjectName, Iterable[ProjectName]]) -> None

    mkdocstrings = ProjectName("mkdocstrings")
    cycle_detected = False
    deps = deque()  # type: Deque[ProjectName]

    deps.extend(lock[mkdocstrings])
    while deps:
        dep = deps.popleft()
        if dep == mkdocstrings:
            cycle_detected = True
            break
        deps.extend(lock[dep])

    assert cycle_detected, "Expected the mkdocstrings lock to contain a cycle."


@pytest.fixture
def lock(tmpdir):
    # type: (Tempdir) -> str

    if IS_PYPY:
        pytest.skip(
            "mkdocstrings 0.30.0 has native deps that are slow to build (MarkupSafe) with no "
            "published wheels for PyPy"
        )
    if sys.version_info[:2] < (3, 9):
        pytest.skip("mkdocstrings 0.30.0 requires Python >= 3.9")

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--elide-unused-requires-dist",
        "mkdocstrings[python]==0.30.0",
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    lockfile = json_codec.load(lockfile_path=lock)
    assert len(lockfile.locked_resolves) == 1
    locked_resolve = lockfile.locked_resolves[0]
    assert_mkdocstrings_lock_cycle(
        {
            locked_requirement.pin.project_name: tuple(
                requirement.project_name for requirement in locked_requirement.requires_dists
            )
            for locked_requirement in locked_resolve.locked_requirements
        }
    )

    return lock


def export_lock(
    lock,  # type: str
    pylock,  # type: str
):
    # type: (...) -> None
    run_pex3("lock", "export", "--format", "pep-751", "-o", pylock, lock).assert_success()


def test_export_cyclic_lock_to_pylock(
    tmpdir,  # type: Tempdir
    lock,  # type: str
):
    # type: (...) -> None

    pylock_toml = tmpdir.join("pylock.toml")
    export_lock(lock, pylock_toml)

    pylock = try_(Pylock.parse(pylock_toml))
    assert_mkdocstrings_lock_cycle(
        {
            package.project_name: tuple(
                dependency.project_name for dependency in (package.dependencies or ())
            )
            for package in pylock.packages
        }
    )


def test_pex_from_cyclic_lock_all(
    tmpdir,  # type: Tempdir
    lock,  # type: str
):
    # type: (...) -> None

    pylock = tmpdir.join("pylock.toml")
    export_lock(lock, pylock)

    pex_root = tmpdir.join("pex-root")

    native_lock_pex = tmpdir.join("pylock.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "-o",
            native_lock_pex,
        ]
    ).assert_success()
    mkdocstrings_path = subprocess.check_output(
        args=[native_lock_pex, "-c", "import mkdocstrings; print(mkdocstrings.__file__)"]
    ).decode("utf-8")
    assert pex_root == commonpath((pex_root, mkdocstrings_path))

    pylock_pex = tmpdir.join("pylock.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pylock",
            pylock,
            "-o",
            pylock_pex,
        ]
    ).assert_success()
    assert mkdocstrings_path == subprocess.check_output(
        args=[pylock_pex, "-c", "import mkdocstrings; print(mkdocstrings.__file__)"]
    ).decode("utf-8")
