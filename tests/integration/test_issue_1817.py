# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil

from pex.cli.testing import run_pex3
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def assert_create_and_use_sdist_lock(
    tmpdir,  # type: Any
    requirement,  # type: str
    test,  # type: str
):
    # type: (...) -> None
    pex_root = os.path.join(str(tmpdir), "pex_root")
    lock = os.path.join(str(tmpdir), "lock.json")

    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--no-wheel",
        requirement,
        "-o",
        lock,
        "--indent",
        "2",
    ).assert_success()

    shutil.rmtree(pex_root)
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "--",
            "-c",
            test,
        ]
    ).assert_success()


def test_sdist_for_project_universal(tmpdir):
    # type: (Any) -> None
    assert_create_and_use_sdist_lock(tmpdir, "ansicolors==1.1.8", "import colors")


def test_sdist_for_project_with_native_extensions(tmpdir):
    # type: (Any) -> None
    assert_create_and_use_sdist_lock(tmpdir, "psutil==5.9.1", "import psutil")


def test_sdist_for_project_with_pep517_build(tmpdir):
    # type: (Any) -> None
    assert_create_and_use_sdist_lock(tmpdir, "PyYAML==5.4.1", "import yaml")
