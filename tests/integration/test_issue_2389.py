# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import PY310, ensure_python_interpreter, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


def test_lock_use_no_build_wheel(tmpdir):
    # type: (Any)-> None

    lock = os.path.join(str(tmpdir), "black.lock")
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
        "--interpreter-constraint",
        "CPython==3.10.*",
        "--wheel",
        "--no-build",
    ).assert_success()

    pex = os.path.join(str(tmpdir), "black.pex")
    python = sys.executable if sys.version_info[:2] == (3, 10) else ensure_python_interpreter(PY310)
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

    output = subprocess.check_output(args=[pex, "--version"])
    assert (
        "black.pex, 22.8.0 (compiled: {compiled})".format(
            compiled="no" if PythonInterpreter.from_binary(python).is_pypy else "yes"
        )
        in output.decode("utf-8").splitlines()
    )
