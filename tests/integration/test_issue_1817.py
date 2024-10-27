# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import sys

import pytest

from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pythonPI import skip_flit_core_39

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


# For test_sdist_for_project_universal and test_sdist_for_project_with_native_extensions the skip is
# needed because we force sdist only which currently transitively applies to build system requires
# which leads to needing to build a wheel for wheel, which uses flit_core.


@skip_flit_core_39
def test_sdist_for_project_universal(tmpdir):
    # type: (Any) -> None
    assert_create_and_use_sdist_lock(tmpdir, "ansicolors==1.1.8", "import colors")


@skip_flit_core_39
def test_sdist_for_project_with_native_extensions(tmpdir):
    # type: (Any) -> None
    assert_create_and_use_sdist_lock(tmpdir, "psutil==5.9.1", "import psutil")


@pytest.mark.skipif(
    sys.version_info < (3, 6) or sys.version_info >= (3, 13),
    reason=(
        "PyYAML 6.0.1 requires Python >= 3.6. PyYAML also requires Cython to build but Cython "
        "(3.0.7) itself fails to build from source under 3.13 due to Python C API changes."
    ),
)
def test_sdist_for_project_with_pep517_build(tmpdir):
    # type: (Any) -> None
    assert_create_and_use_sdist_lock(tmpdir, "PyYAML==6.0.1", "import yaml")
