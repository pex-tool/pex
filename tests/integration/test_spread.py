# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys

import pytest

from pex.common import safe_open, safe_rmtree
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List


@pytest.mark.parametrize(
    "mode_args",
    [
        pytest.param(["--spread"], id="Spread"),
        pytest.param(["--spread", "--venv"], id="Spread VENV"),
    ],
)
def test_resiliency(
    tmpdir,  # type: Any
    mode_args,  # type: List[str]
):
    # type: (...) -> None
    src_dir = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src_dir, "exe.py"), "w") as fp:
        fp.write("import colors; print(colors.__version__)")

    pex_root = os.path.join(str(tmpdir), "pex_root")
    spread = os.path.join(str(tmpdir), "spread")

    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "ansicolors==1.1.8",
            "-D",
            src_dir,
            "-e",
            "exe",
            "-o",
            spread,
        ]
        + mode_args
    ).assert_success()

    def assert_exe(*args):
        # type: (*str) -> None
        output = subprocess.check_output(args=args)
        assert b"1.1.8\n" == output

    spread_pex = os.path.join(spread, "pex")
    assert_exe(sys.executable, spread)
    assert_exe(spread_pex)

    safe_rmtree(pex_root)
    assert_exe(spread_pex)
    assert_exe(sys.executable, spread)
