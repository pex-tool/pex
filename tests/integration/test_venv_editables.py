# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import subprocess
import sys

import pytest

from pex.venv.virtualenv import Virtualenv
from testing.cli import run_pex3
from testing.local_project import LocalProject
from testing.local_project import create as create_local_project
from testing.pytest_utils.tmp import Tempdir

skip_too_old_setuptools = pytest.mark.skipif(
    sys.version_info < (3, 7),
    reason=(
        "Modern setuptools (>= 64.0.0) with support for pep-660 build_editable is required, and "
        "setuptools 64 requires at least Python 3.7."
    ),
)


@pytest.fixture
def local_project(tmpdir):
    # type: (Tempdir) -> LocalProject
    return create_local_project(tmpdir.join("project"))


@skip_too_old_setuptools
def test_venv_create_pip(
    tmpdir,  # type: Tempdir
    local_project,  # type: LocalProject
):
    # type: (...) -> None

    venv_dir = tmpdir.join("venv")
    run_pex3("venv", "create", local_project, "-d", venv_dir).assert_success()
    local_project_script = Virtualenv(venv_dir).bin_path("local-project")

    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])
    local_project.edit_all_caps(True)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])

    run_pex3("venv", "create", "-e", local_project, "-d", venv_dir, "--force").assert_success()
    assert b"FOO" == subprocess.check_output(args=[local_project_script, "foo"])
    local_project.edit_all_caps(False)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])


@pytest.fixture
def pex_lock(
    tmpdir,  # type: Tempdir
    local_project,  # type: LocalProject
):
    # type: (...) -> str
    pex_lock = tmpdir.join("lock.json")
    run_pex3("lock", "create", local_project, "--indent", "2", "-o", pex_lock).assert_success()
    return pex_lock


@skip_too_old_setuptools
def test_venv_create_pex_lock(
    tmpdir,  # type: Tempdir
    pex_lock,  # type: str
    local_project,  # type: LocalProject
):
    # type: (...) -> None

    venv_dir = tmpdir.join("venv")
    run_pex3("venv", "create", "--lock", pex_lock, "-d", venv_dir).assert_success()
    local_project_script = Virtualenv(venv_dir).bin_path("local-project")

    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])
    local_project.edit_all_caps(True)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])

    run_pex3(
        "venv",
        "create",
        "--override=-e local_project @ {local_project}".format(local_project=local_project),
        "--lock",
        pex_lock,
        "-d",
        venv_dir,
        "--force",
    ).assert_success()
    assert b"FOO" == subprocess.check_output(args=[local_project_script, "foo"])
    local_project.edit_all_caps(False)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])


@pytest.fixture
def pylock(
    tmpdir,  # type: Tempdir
    pex_lock,  # type: str
):
    # type: (...) -> str
    pylock = tmpdir.join("pylock.toml")
    # pep-751
    run_pex3("lock", "export", "--format", "pep-751", "-o", pylock, pex_lock).assert_success()
    return pylock


@skip_too_old_setuptools
def test_venv_create_pylock(
    tmpdir,  # type: Tempdir
    pylock,  # type: str
    local_project,  # type: LocalProject
):
    # type: (...) -> None

    venv_dir = tmpdir.join("venv")
    run_pex3("venv", "create", "--pylock", pylock, "-d", venv_dir).assert_success()
    local_project_script = Virtualenv(venv_dir).bin_path("local-project")

    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])
    local_project.edit_all_caps(True)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])

    run_pex3(
        "venv",
        "create",
        "--override=-e local_project @ file:{local_project}".format(local_project=local_project),
        "--pylock",
        pylock,
        "-d",
        venv_dir,
        "--force",
    ).assert_success()
    assert b"FOO" == subprocess.check_output(args=[local_project_script, "foo"])
    local_project.edit_all_caps(False)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])


@skip_too_old_setuptools
def test_run(
    tmpdir,  # type: Tempdir
    local_project,  # type: LocalProject
):
    # type: (...) -> None

    run_pex3("run", "--from", local_project, "local-project", "bar").assert_success(
        expected_output_re="bar"
    )
    local_project.edit_all_caps(True)
    run_pex3("run", "--from", local_project, "local-project", "bar").assert_success(
        expected_output_re="bar"
    )

    run_pex3(
        "run",
        "--from=-e {local_project}".format(local_project=local_project),
        "local-project",
        "bar",
    ).assert_success(expected_output_re="BAR")
    local_project.edit_all_caps(False)
    run_pex3(
        "run",
        "--from=-e {local_project}".format(local_project=local_project),
        "local-project",
        "bar",
    ).assert_success(expected_output_re="bar")
