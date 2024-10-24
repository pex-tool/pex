# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
import subprocess

from testing import make_env, run_pex_command
from testing.pytest.tmp import Tempdir


def test_symlinked_home(tmpdir):
    # type: (Tempdir) -> None

    real_home = tmpdir.join("a", "b", "c")
    symlinked_home = tmpdir.join("lnk")
    os.symlink(real_home, symlinked_home)

    pex = tmpdir.join("pex")
    run_pex_command(
        args=["cowsay==5.0", "-c", "cowsay", "-o", pex], env=make_env(HOME=symlinked_home)
    ).assert_success()

    def test_pex():
        # type: () -> None
        assert (
            "5.0"
            == subprocess.check_output(args=[pex, "--version"], env=make_env(HOME=symlinked_home))
            .decode("utf-8")
            .strip()
        )

    test_pex()

    shutil.rmtree(real_home)
    os.makedirs(real_home)
    test_pex()
