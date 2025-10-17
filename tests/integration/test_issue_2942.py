# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess

import pytest

from testing import PY_VER, run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    PY_VER >= (3, 15),
    reason="This test requires installing Pex <2.60 of which none support Python >=3.15.",
)
def test_pex_tools_venv_backwards_compatibility(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    old_pex = tmpdir.join("old.pex")
    run_pex_command(
        args=[
            "pex<2.60",
            "-c",
            "pex",
            "--",
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "cowsay<6",
            "-c",
            "cowsay",
            "-o",
            old_pex,
        ]
    ).assert_success()

    venv_dir = tmpdir.join("new.venv")
    run_pex_command(args=[old_pex, "venv", venv_dir], pex_module="pex.tools").assert_success()
    assert b"| Moo! |" in subprocess.check_output(args=[os.path.join(venv_dir, "pex"), "Moo!"])
