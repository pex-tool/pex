# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess

from pex.interpreter import PythonInterpreter
from pex.os import is_exe
from pex.venv.virtualenv import Virtualenv
from testing import make_env
from testing.pytest_utils.tmp import Tempdir


def test_pex_pex_pex_python_path(
    tmpdir,  # type: Tempdir
    py310,  # type: PythonInterpreter
    py311,  # type: PythonInterpreter
):
    # type: (...) -> None

    dist_dir = tmpdir.join("dist")

    # The package command can be slow to run which locks up uv; so we just ensure a synced
    # uv venv (fast), then run the dev-cmd console script directly to avoid uv lock
    # timeouts in CI.
    subprocess.check_call(args=["uv", "sync", "--frozen"])
    subprocess.check_call(
        args=[Virtualenv(".venv").bin_path("dev-cmd"), "package", "--", "--dist-dir", dist_dir]
    )
    pex_pex = os.path.join(dist_dir, "pex")
    assert is_exe(pex_pex)

    def assert_python_selected(
        expected_python,  # type: str
        **env  # type: str
    ):
        # type: (...) -> None

        assert (
            os.path.realpath(expected_python)
            == subprocess.check_output(
                args=[
                    pex_pex,
                    "--interpreter-constraint",
                    ">=3.10,<3.12",
                    "--",
                    "-c",
                    "import sys, os; print(os.path.realpath(sys.executable))",
                ],
                env=make_env(**env),
            )
            .decode("utf-8")
            .strip()
        )

    assert_python_selected(py310.binary, PEX_PYTHON_PATH=py310.binary)
    assert_python_selected(py311.binary, PEX_PYTHON_PATH=py311.binary)
