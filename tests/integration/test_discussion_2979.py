# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os.path
import shutil
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
                requires = ["uv_build>=0.9.6,<0.10.0"]
                build-backend = "uv_build"

                [project]
                name = "project"
                version = "0.42.0"
                description = "Repro of https://github.com/pex-tool/pex/discussions/2979"
                requires-python = "==3.10.*"
                dependencies = [
                    "anywidget<0.10.0,>=0.9.14",

                    # Internal only.
                    # "corr_module>=1.0.0",

                    # Because only marketdata<=0.2.0 is available and your project depends on marketdata>=2.0.0,<3.0.0, we can conclude that your project's requirements are unsatisfiable.
                    # "marketdata<3.0.0,>=2.0.0",
                    "marketdata",

                    "matplotlib<4.0.0,>=3.7.0",
                    "numpy<3.0.0,>=2.2.3",
                    "openpyxl<4.0.0,>=3.1.5",
                    "plotly<6.0.0,>=5.24.1",
                    "polars<2.0.0,>=1.32.3",
                    "pyyaml<7.0.0,>=6.0.2",
                    "scikit-learn<2.0.0,>=1.6.1",
                    "scipy<2.0.0,>=1.15.0",
                    "statsmodels<0.15.0,>=0.14.4",

                    # Because only tsm>=8.0 is available and your project depends on tsm>=2.0.11,<3.0.0, we can conclude that your project's requirements are unsatisfiable.
                    # "tsm<3.0.0,>=2.0.11",
                    "tsm",

                    # Internal only.
                    # "utils-internal==1.0.11"
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


def assert_project(
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
                dedent(
                    """\
                import json
                import sys
                from importlib import metadata

                import project
                import scipy


                json.dump(
                    {
                        "project_path": project.__file__,
                        "project_version": metadata.version("project"),
                        "scipy_path": scipy.__file__,
                    },
                    sys.stdout,
                )
                """
                ),
            ]
        )
        .decode("utf-8")
        .strip()
    )

    data = json.loads(output)
    assert pex_root == commonpath((pex_root, data["project_path"]))
    assert "0.42.0" == data["project_version"]
    assert pex_root == commonpath((pex_root, data["scipy_path"]))


def test_venv_subset_with_specifiers_discussion_op(
    tmpdir,  # type: Tempdir
    project_dir,  # type: str
    project_venv,  # type: Virtualenv
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
            "scipy",
            "--project",
            project_dir,
            "-o",
            pex,
            "--no-compress",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()

    assert_project(python=project_venv.interpreter, pex_root=pex_root, pex=pex)


def test_editable_installs_subset_issue_2982(
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
    ).assert_success()

    shutil.rmtree(project_dir)
    assert_project(python=py310, pex_root=pex_root, pex=pex)


def test_editable_installs_full_resolve_issue_2982(
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
            "-o",
            pex,
            "--no-compress",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()

    shutil.rmtree(project_dir)
    assert_project(python=py310, pex_root=pex_root, pex=pex)
