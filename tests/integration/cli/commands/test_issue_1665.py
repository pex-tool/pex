# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

import pytest

from pex.cli.testing import run_pex3
from pex.testing import IS_PYPY, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    IS_PYPY or sys.version_info[:3] < (3, 6, 2),
    reason="The black 22.3.0 distribution requires Python >= 3.6.2",
)
def test_lock_black(tmpdir):
    # type: (Any) -> None

    lock = os.path.join(str(tmpdir), "lock")
    run_pex3(
        "lock",
        "create",
        "--resolver-version",
        "pip-2020-resolver",
        "--style",
        "universal",
        "black==22.3.0",
        "-o",
        lock,
    ).assert_success()
    result = run_pex_command(args=["--lock", lock, "-c", "black", "--", "--version"])
    result.assert_success()
    assert " 22.3.0 " in result.output
