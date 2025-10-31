# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
from textwrap import dedent

from pex.common import safe_open, touch
from pex.compatibility import commonpath
from pex.venv.virtualenv import Virtualenv
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_venv_subset_with_specifiers(tmpdir):
    # type: (Tempdir) -> None

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

    subprocess.check_call(args=["uv", "sync"], cwd=project_dir)
    venv = Virtualenv(os.path.join(project_dir, ".venv"))

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
            os.path.join(project_dir, ".venv"),
            "scipy",
            "--project",
            project_dir,
            "-o",
            pex,
            "--no-compress",
        ],
        python=venv.interpreter.binary,
    ).assert_success()

    assert pex_root == commonpath(
        (
            pex_root,
            subprocess.check_output(
                args=[venv.interpreter.binary, pex, "-c", "import scipy; print(scipy.__file__)"]
            )
            .decode("utf-8")
            .strip(),
        )
    )
    assert (
        b"0.42.0"
        == subprocess.check_output(
            args=[
                venv.interpreter.binary,
                pex,
                "-c",
                "from importlib import metadata; print(metadata.version('project'))",
            ]
        ).strip()
    )
