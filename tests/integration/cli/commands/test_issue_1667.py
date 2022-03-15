# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

import pytest

from pex.cli.testing import run_pex3
from pex.interpreter import PythonInterpreter
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[0] < 3,
    reason=(
        "The lock under test takes ~infinite time to generate under Python 2.7 using the "
        "pip-2020-resolver. Since the original issue and even this use in-the-small will "
        "by-definition never try to use a Python 2.7 interpreter to perform the lock, simply avoid "
        "the issue."
    ),
)
def test_interpreter_constraints_range_coverage(
    tmpdir,  # type: Any
    py37,  # type: PythonInterpreter
):
    # type: (...) -> None

    # We lock with an unconstrained IPython requirement and we know IPython latest does not support
    # Python 3.7. If locking respects ICs it should not pick latest, but a version that supports at
    # least 3.7
    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--resolver-version",
        "pip-2020-resolver",
        "--interpreter-constraint",
        ">=3.7,<3.11",
        "ipython",
        "-o",
        lock,
    ).assert_success()

    pex_root = os.path.join(str(tmpdir), "pex_root")
    ipython_pex = os.path.join(str(tmpdir), "ipython.pex")
    run_pex_command(
        args=[
            "--interpreter-constraint",
            ">=3.7,<3.11",
            "--lock",
            lock,
            "-c",
            "ipython",
            "-o",
            ipython_pex,
            "--runtime-pex-root",
            pex_root,
        ],
    ).assert_success()

    run_ipython_args = [ipython_pex, "-c", "import IPython; print(IPython.__file__)"]
    output = subprocess.check_output(args=[py37.binary] + run_ipython_args)
    assert output.decode("utf-8").strip().startswith(pex_root)

    if (3, 7) <= sys.version_info[:2] < (3, 11):
        output = subprocess.check_output(args=[sys.executable] + run_ipython_args)
        assert output.decode("utf-8").strip().startswith(pex_root)
