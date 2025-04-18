# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess

import pytest

from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider

if TYPE_CHECKING:
    from typing import List


@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--sh-boot"], id="SH_BOOT"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-SH_BOOT"),
    ],
)
@skip_if_no_provider
def test_scie_argv0(
    tmpdir,  # type: Tempdir
    pex_wheel,  # type: str
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex_pex = tmpdir.join("pex.pex")
    run_pex_command(
        args=[pex_wheel, "-c", "pex", "-o", pex_pex, "--scie", "eager"] + execution_mode_args
    ).assert_success()

    def assert_argv0(exe):
        # type: (str) -> None

        # N.B.: The Pex CLI uses argparse and argparse defaults prog to
        # `os.path.basename(sys.argv[0])`; so this test indirectly tests sys.argv[0] setup but the
        # PEX boot process.
        expected_argv0 = os.path.basename(exe)
        help_line1 = subprocess.check_output(args=[exe, "-h"]).decode("utf-8").splitlines()[0]
        assert (
            "usage: {expected_argv0} [-o OUTPUT.PEX] [options] [-- arg1 arg2 ...]".format(
                expected_argv0=expected_argv0
            )
            == help_line1
        )

    assert_argv0(pex_pex)
    assert_argv0(tmpdir.join("pex"))
