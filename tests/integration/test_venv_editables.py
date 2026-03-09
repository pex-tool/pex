# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os.path
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.venv.virtualenv import Virtualenv
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


@pytest.fixture
def local_project(tmpdir):
    # type: (Tempdir) -> str

    local_project_dir = tmpdir.join("project")
    with safe_open(os.path.join(local_project_dir, "local_project.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from __future__ import print_function

                import sys


                ALL_CAPS = False


                def main():
                    text = sys.argv[1:]
                    if ALL_CAPS:
                        text[:] = [item.upper() for item in text]
                    print(*text, end="")

                """
            )
        )
    with safe_open(os.path.join(local_project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = local_project
                version = 0.0.1

                [options]
                py_modules =
                    local_project

                [options.entry_points]
                console_scripts =
                    local-project = local_project:main
                """
            )
        )
    with safe_open(os.path.join(local_project_dir, "setup.py"), "w") as fp:
        fp.write("from setuptools import setup; setup()")
    with open(os.path.join(local_project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
    return local_project_dir


def edit_local_project_all_caps(
    local_project_dir,  # type: str
    all_caps,  # type: bool
):
    # type: (...) -> None

    with open(os.path.join(local_project_dir, "local_project.py"), "a") as fp:
        print("ALL_CAPS={all_caps!r}".format(all_caps=all_caps), file=fp)


skip_too_old_setuptools = pytest.mark.skipif(
    sys.version_info < (3, 7),
    reason=(
        "Modern setuptools (>= 64.0.0) with support for pep-660 build_editable is required, and "
        "setuptools 64 requires at least Python 3.7."
    ),
)


@skip_too_old_setuptools
def test_venv_create_pip(
    tmpdir,  # type: Tempdir
    local_project,  # type: str
):
    # type: (...) -> None

    venv_dir = tmpdir.join("venv")
    run_pex3("venv", "create", local_project, "-d", venv_dir).assert_success()
    local_project_script = Virtualenv(venv_dir).bin_path("local-project")

    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])
    edit_local_project_all_caps(local_project, all_caps=True)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])

    run_pex3("venv", "create", "-e", local_project, "-d", venv_dir, "--force").assert_success()
    assert b"FOO" == subprocess.check_output(args=[local_project_script, "foo"])
    edit_local_project_all_caps(local_project, all_caps=False)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])


@pytest.fixture
def pex_lock(
    tmpdir,  # type: Tempdir
    local_project,  # type: str
):
    # type: (...) -> str
    pex_lock = tmpdir.join("lock.json")
    run_pex3("lock", "create", local_project, "--indent", "2", "-o", pex_lock).assert_success()
    return pex_lock


@skip_too_old_setuptools
def test_venv_create_pex_lock(
    tmpdir,  # type: Tempdir
    pex_lock,  # type: str
    local_project,  # type: str
):
    # type: (...) -> None

    venv_dir = tmpdir.join("venv")
    run_pex3("venv", "create", "--lock", pex_lock, "-d", venv_dir).assert_success()
    local_project_script = Virtualenv(venv_dir).bin_path("local-project")

    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])
    edit_local_project_all_caps(local_project, all_caps=True)
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
    edit_local_project_all_caps(local_project, all_caps=False)
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
    local_project,  # type: str
):
    # type: (...) -> None

    venv_dir = tmpdir.join("venv")
    run_pex3("venv", "create", "--pylock", pylock, "-d", venv_dir).assert_success()
    local_project_script = Virtualenv(venv_dir).bin_path("local-project")

    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])
    edit_local_project_all_caps(local_project, all_caps=True)
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
    edit_local_project_all_caps(local_project, all_caps=False)
    assert b"foo" == subprocess.check_output(args=[local_project_script, "foo"])


@skip_too_old_setuptools
def test_run(
    tmpdir,  # type: Tempdir
    local_project,  # type: str
):
    # type: (...) -> None

    run_pex3("run", "--from", local_project, "local-project", "bar").assert_success(
        expected_output_re="bar"
    )
    edit_local_project_all_caps(local_project, all_caps=True)
    run_pex3("run", "--from", local_project, "local-project", "bar").assert_success(
        expected_output_re="bar"
    )

    run_pex3(
        "run",
        "--from=-e {local_project}".format(local_project=local_project),
        "local-project",
        "bar",
    ).assert_success(expected_output_re="BAR")
    edit_local_project_all_caps(local_project, all_caps=False)
    run_pex3(
        "run",
        "--from=-e {local_project}".format(local_project=local_project),
        "local-project",
        "bar",
    ).assert_success(expected_output_re="bar")
