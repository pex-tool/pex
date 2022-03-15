# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

import pytest

from pex.cli.testing import run_pex3
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 7) or sys.version_info[:2] >= (3, 11),
    reason="The lock under test requires an interpreter satisfying >=3.7,<3.11 to test against.",
)
def test_interpreter_constraints_range_coverage(tmpdir):
    # type: (Any) -> None

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

    output = subprocess.check_output(
        args=[ipython_pex, "-c", "import IPython; print(IPython.__file__)"]
    )
    assert output.decode("utf-8").strip().startswith(pex_root)
