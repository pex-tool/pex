# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

import pytest

from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    IS_PYPY or sys.version_info[:3] < (3, 6, 2),
    reason="The black 22.3.0 distribution requires Python >= 3.6.2",
)
def test_lock_black(tmpdir):
    # type: (Any) -> None

    lock = os.path.join(str(tmpdir), "lock")
    lock_create_args = (
        "lock",
        "create",
        "--resolver-version",
        "pip-2020-resolver",
        "--style",
        "universal",
        "black==22.3.0",
        "-o",
        lock,
    )

    def assert_lock(*extra_lock_args, **extra_popen_args):
        run_pex3(*(lock_create_args + extra_lock_args), **extra_popen_args).assert_success()
        result = run_pex_command(args=["--lock", lock, "-c", "black", "--", "--version"])
        result.assert_success()
        assert " 22.3.0 " in result.output

    assert_lock()

    cwd = os.path.join(str(tmpdir), "cwd")
    tmpdir = os.path.join(cwd, ".tmp")
    os.makedirs(tmpdir)
    assert_lock("--tmpdir", ".tmp", cwd=cwd)
