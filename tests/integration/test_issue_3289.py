# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess

import pytest

from pex.interpreter import PythonInterpreter
from testing import IS_WINDOWS, make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir

skip_if_windows = pytest.mark.skipif(
    IS_WINDOWS, reason="The `--sh-boot` option under test is only for unix targets."
)


@pytest.fixture
def pex(tmpdir):
    # type: (Tempdir) -> str

    pex = tmpdir.join("pex")
    pex_root = tmpdir.join("pex-root")
    run_pex_command(
        args=[
            "--runtime-pex-root",
            pex_root,
            "--sh-boot",
            "--python-shebang",
            "/nonexistent/python",
            "-o",
            pex,
        ]
    ).assert_success()
    return pex


@skip_if_windows
def test_sh_boot_respects_pex_python(
    tmpdir,  # type: Tempdir
    pex,  # type: str
    py311,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert (
        py311.binary
        == subprocess.check_output(
            args=[pex, "-c", "import sys; print(sys.executable)"],
            env=make_env(PATH="/nonexistent", PEX_PYTHON=py311.binary),
        )
        .decode("utf-8")
        .strip()
    )


@skip_if_windows
def test_sh_boot_respects_pex_python_path(
    tmpdir,  # type: Tempdir
    pex,  # type: str
    py311,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert (
        py311.binary
        == subprocess.check_output(
            args=[pex, "-c", "import sys; print(sys.executable)"],
            env=make_env(
                PATH="/nonexistent", PEX_PYTHON_PATH=":".join(("/also/dne", py311.binary))
            ),
        )
        .decode("utf-8")
        .strip()
    )

    assert (
        py311.binary
        == subprocess.check_output(
            args=[pex, "-c", "import sys; print(sys.executable)"],
            env=make_env(
                PATH="/nonexistent",
                PEX_PYTHON_PATH=":".join(("/also/dne", os.path.dirname(py311.binary))),
            ),
        )
        .decode("utf-8")
        .strip()
    )
