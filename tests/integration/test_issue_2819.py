# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess

from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_tmp_dir_leak(
    tmpdir,  # type: Tempdir
    fake_system_tmp_dir,  # type: str
):
    # type: (...) -> None

    assert [] == os.listdir(fake_system_tmp_dir)

    pex = tmpdir.join("pex")
    pex_root = tmpdir.join("pex_root")
    run_pex_command(
        args=[
            "cowsay<6",
            "-c",
            "cowsay",
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "-o",
            pex,
            "--no-pre-install-wheels",
        ]
    ).assert_success()
    assert [] == os.listdir(fake_system_tmp_dir)

    assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"])
    assert [] == os.listdir(fake_system_tmp_dir)
