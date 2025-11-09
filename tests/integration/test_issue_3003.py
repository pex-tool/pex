# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open, touch
from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from pex.venv.virtualenv import Virtualenv
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.fixture
def project_dir(tmpdir):
    # type: (Tempdir) -> str

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["uv_build>=0.9,<0.10.0"]
                build-backend = "uv_build"

                [project]
                name = "project"
                version = "0.42.0"
                description = "Repro of issue 3003"
                requires-python = "==3.10.*"
                dependencies = [
                    "opentelemetry-semantic-conventions==0.59b0",
                ]
                """
            )
        )
    touch(os.path.join(project_dir, "src", "project", "__init__.py"))
    return project_dir


@pytest.fixture
def project_venv(project_dir):
    # type: (str) -> Virtualenv

    subprocess.check_call(args=["uv", "sync"], cwd=project_dir)
    return Virtualenv(os.path.join(project_dir, ".venv"))


def assert_opentelemetry_semconv(
    python,  # type: PythonInterpreter
    pex_root,  # type: str
    pex,  # type: str
):
    # type: (...) -> None

    output = (
        subprocess.check_output(
            args=[
                python.binary,
                pex,
                "-c",
                "from opentelemetry import semconv; print(semconv.__file__)",
            ]
        )
        .decode("utf-8")
        .strip()
    )

    assert pex_root == commonpath((pex_root, output))


def test_edge_case_semver_version_satisfied(
    tmpdir,  # type: Tempdir
    project_dir,  # type: str
    project_venv,  # type: Virtualenv
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("project.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pip-version",
            "latest-compatible",
            "--venv-repository",
            project_venv.venv_dir,
            "project",
            "-o",
            pex,
            "--no-compress",
        ],
        python=project_venv.interpreter.binary,
    ).assert_failure(
        expected_error_re=r".*^{error_msg}$".format(
            error_msg=re.escape(
                "Resolve from venv at {venv_dir} failed: The virtual environment has "
                "opentelemetry-semantic-conventions 0.59b0 installed but it does not meet top "
                "level requirement project -> opentelemetry-semantic-conventions==0.59b0.".format(
                    venv_dir=project_venv.venv_dir
                )
            ),
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )

    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pip-version",
            "latest-compatible",
            "--venv-repository",
            project_venv.venv_dir,
            "project",
            "-o",
            pex,
            "--no-compress",
            "--pre",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()
    assert_opentelemetry_semconv(python=py310, pex_root=pex_root, pex=pex)

    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pip-version",
            "latest-compatible",
            "--venv-repository",
            project_venv.venv_dir,
            "opentelemetry-semantic-conventions==0.59b0",
            "-o",
            pex,
            "--no-compress",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()
    assert_opentelemetry_semconv(python=py310, pex_root=pex_root, pex=pex)
