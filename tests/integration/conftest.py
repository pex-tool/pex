# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
import subprocess

import pytest

from pex.common import atomic_directory, safe_mkdir
from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture(scope="session")
def is_pytest_xdist(worker_id):
    # type: (str) -> bool
    return worker_id != "master"


@pytest.fixture(scope="session")
def shared_integration_test_tmpdir(
    tmpdir_factory,  # type: Any
    is_pytest_xdist,  # type: bool
):
    # type: (...) -> str
    tmpdir = str(tmpdir_factory.getbasetemp())

    # We know pytest-xdist creates a subdir under the pytest session tmp dir for each worker; so we
    # go up a level to lock a directory all workers can use.
    if is_pytest_xdist:
        tmpdir = os.path.dirname(tmpdir)

    return os.path.join(tmpdir, "shared_integration_test_tmpdir")


@pytest.fixture(scope="session")
def pex_bdist(
    pex_project_dir,  # type: str
    shared_integration_test_tmpdir,  # type: str
):
    # type: (...) -> str
    pex_bdist_chroot = os.path.join(shared_integration_test_tmpdir, "pex_bdist_chroot")
    wheels_dir = os.path.join(pex_bdist_chroot, "wheels_dir")
    with atomic_directory(pex_bdist_chroot, exclusive=True) as chroot:
        if not chroot.is_finalized:
            pex_pex = os.path.join(pex_bdist_chroot, "pex.pex")
            run_pex_command(
                args=[pex_project_dir, "-o", pex_pex, "--include-tools"]
            ).assert_success()
            subprocess.check_call(
                args=[pex_pex, "repository", "extract", "-f", wheels_dir],
                env=make_env(PEX_TOOLS=True),
            )
    wheels = os.listdir(wheels_dir)
    assert 1 == len(wheels)
    return os.path.join(wheels_dir, wheels[0])


@pytest.fixture(scope="session")
def pex_src(
    pex_project_dir,  # type: str
    shared_integration_test_tmpdir,  # type: str
):
    # type: (...) -> str
    src = os.path.join(shared_integration_test_tmpdir, "pex_src")
    for root, dirs, files in os.walk(os.path.join(pex_project_dir, "pex")):
        root_relpath = os.path.relpath(root, pex_project_dir)
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for d in dirs:
            safe_mkdir(os.path.join(src, root_relpath, d))
        for f in files:
            if not f.endswith(".pyc"):
                shutil.copy(os.path.join(root, f), os.path.join(src, root_relpath, f))
    return src
