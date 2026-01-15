# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import safe_mkdir
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import List


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 7),
    reason="The fortune 1.1.1 distribution uses Python 3.7 syntax and features.",
)
@pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="zipapp"), pytest.param(["--venv"], id="venv")]
)
def test_bind_resource_path(
    tmpdir,  # type: Tempdir
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    fortune = tmpdir.join("fortune.pex")
    chroot = tmpdir.join("chroot")
    with open(
        os.path.join(safe_mkdir(os.path.join(chroot, "resources")), "fortunes.dat"), "w"
    ) as fp:
        fp.write(
            dedent(
                """\
                A day for firm decisions!!!!!  Or is it?
                %
                """
            )
        )

    run_pex_command(
        args=[
            "fortune==1.1.1",
            "-c",
            "fortune",
            "-D",
            chroot,
            "--inject-args",
            "{pex.env.FORTUNE_FILE}",
            "--bind-resource-path",
            "FORTUNE_FILE=resources/fortunes.dat",
            "-o",
            fortune,
        ]
        + execution_mode_args
    ).assert_success()

    assert b"A day for firm decisions!!!!!  Or is it?\n" == subprocess.check_output(args=[fortune])
