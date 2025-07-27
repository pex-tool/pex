# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

from pex.interpreter import PythonInterpreter
from testing import run_pex_command, subprocess
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


def test_lock_use_no_build_wheel(
    tmpdir,  # type: Tempdir
    py310,  # type: PythonInterpreter
):
    # type: (...)-> None

    lock = tmpdir.join("black.lock")
    run_pex3(
        "lock",
        "create",
        "black==22.8.0",
        "-o",
        lock,
        "--style",
        "universal",
        "--indent",
        "2",
        "--python-path",
        py310.binary,
        "--interpreter-constraint",
        "CPython==3.10.*",
        "--wheel",
        "--no-build",
    ).assert_success()

    pex = tmpdir.join("black.pex")
    python = sys.executable if sys.version_info[:2] == (3, 10) else py310.binary
    run_pex_command(
        args=[
            "-o",
            pex,
            "--python",
            python,
            "-c",
            "black",
            "--lock",
            lock,
            "--wheel",
            "--no-build",
        ]
    ).assert_success()

    output = subprocess.check_output(args=[python, pex, "--version"])
    assert (
        "black.pex, 22.8.0 (compiled: {compiled})".format(
            compiled="no" if PythonInterpreter.from_binary(python).is_pypy else "yes"
        )
        in output.decode("utf-8").splitlines()
    )
