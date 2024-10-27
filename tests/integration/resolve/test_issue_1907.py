# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os.path
import re
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.atomic_directory import atomic_directory
from pex.common import safe_open
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.pip.version import PipVersion
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER, data, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


skip_unless_supports_devpi_server_lock = pytest.mark.skipif(
    PY_VER < (3, 10) or PY_VER >= (3, 14), reason="The uses a lock that requires Python>=3.10,<3.14"
)


@pytest.fixture(scope="session")
def dists(shared_integration_test_tmpdir):
    # type: (str) -> str
    test_issue_1907_chroot = os.path.join(shared_integration_test_tmpdir, "test_issue_1907_chroot")
    with atomic_directory(test_issue_1907_chroot) as chroot:
        if not chroot.is_finalized():
            requirements = os.path.join(chroot.work_dir, "requirements.txt")
            lock = data.path("locks", "devpi-server.lock.json")
            run_pex3("lock", "export", "--format", "pip", lock, "-o", requirements).assert_success()
            dists = os.path.join(chroot.work_dir, "dists")
            subprocess.check_call(
                args=[sys.executable, "-m", "pip", "download", "-r", requirements, "-d", dists]
            )
    return os.path.join(test_issue_1907_chroot, "dists")


@skip_unless_supports_devpi_server_lock
def test_pre_resolved_dists_nominal(
    tmpdir,  # type: Any
    dists,  # type: str
):
    # type: (...) -> None

    run_pex_command(
        args=[
            "--pre-resolved-dists",
            dists,
            "devpi-server",
            "-c",
            "devpi-server",
            "--",
            "--version",
        ]
    ).assert_success(expected_output_re=re.escape("6.12.1"))


@skip_unless_supports_devpi_server_lock
def test_pre_resolved_dists_subset(
    tmpdir,  # type: Any
    dists,  # type: str
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["--pre-resolved-dists", dists, "pyramid", "-c", "pdistreport", "-o", pex]
    ).assert_success()

    assert not any(
        dist
        for dist in PEX(pex).resolve()
        if ProjectName("devpi-server") == dist.metadata.project_name
    ), "The subset should not include devpi-server."

    assert subprocess.check_output(args=[pex]).startswith(b"Pyramid version: 2.0.2")


@pytest.fixture
def local_project(tmpdir):
    # type: (Any) -> str

    project = os.path.join(str(tmpdir), "project")
    with safe_open(os.path.join(project, "app.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                from pyramid.scripts.pdistreport import main


                if __name__ == "__main__":
                    sys.stdout.write("app: ")
                    main()
                """
            )
        )
    with safe_open(os.path.join(project, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"

                [project]
                name = "app"
                version = "0.1.0"
                dependencies = ["pyramid"]
                """
            )
        )
    return project


@skip_unless_supports_devpi_server_lock
def test_pre_resolved_dists_local_project_requirement(
    tmpdir,  # type: Any
    dists,  # type: str
    local_project,  # type: str
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["--pre-resolved-dists", dists, local_project, "-m", "app", "-o", pex]
    ).assert_success()

    assert subprocess.check_output(args=[pex]).startswith(b"app: Pyramid version: 2.0.2")


@skip_unless_supports_devpi_server_lock
def test_pre_resolved_dists_project_requirement(
    tmpdir,  # type: Any
    dists,  # type: str
    local_project,  # type: str
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["--pre-resolved-dists", dists, "--project", local_project, "-m", "app", "-o", pex]
    ).assert_success()

    assert subprocess.check_output(args=[pex]).startswith(b"app: Pyramid version: 2.0.2")


@skip_unless_supports_devpi_server_lock
def test_pre_resolved_dists_offline(
    tmpdir,  # type: Any
    dists,  # type: str
    local_project,  # type: str
):
    # type: (...) -> None

    offline = os.path.join(str(tmpdir), "offline")
    os.mkdir(offline)

    if IS_PYPY or PipVersion.DEFAULT is not PipVersion.VENDORED:
        args = [sys.executable, "-m", "pip", "wheel", "-w", offline]
        if PipVersion.DEFAULT is not PipVersion.VENDORED:
            # In order to go offline and still be able to build sdists, we need both the un-vendored Pip and
            # its basic build requirements.
            args.extend(str(req) for req in PipVersion.DEFAULT.requirements)
        if IS_PYPY:
            # For PyPy, we need extra build dependencies for argon2-cffi-bindings.
            args.append("setuptools_scm")
        subprocess.check_call(args)

    for dist in glob.glob(os.path.join(dists, "*")):
        dest_dist = os.path.join(offline, os.path.basename(dist))
        if not os.path.exists(dest_dist):
            os.symlink(dist, dest_dist)

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--no-pypi",
            "--find-links",
            offline,
            "--pre-resolved-dists",
            offline,
            "--project",
            local_project,
            "-m",
            "app",
            "-o",
            pex,
        ]
    ).assert_success()

    assert subprocess.check_output(args=[pex]).startswith(b"app: Pyramid version: 2.0.2")
