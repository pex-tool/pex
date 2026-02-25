# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess

from pex.common import touch
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_local_venv_package(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("cowsay.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "cowsay<6",
            "-c",
            "cowsay",
            "-o",
            pex,
            "--venv",
        ]
    ).assert_success()

    cwd = tmpdir.join("chroot")
    touch(os.path.join(cwd, "venv", "__init__.py"))
    assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"], cwd=cwd)
