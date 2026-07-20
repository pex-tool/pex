# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
import os.path
import subprocess

from pex.sysconfig import SysPlatform
from testing import make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider


@skip_if_no_provider
def test_scie_only_split_pack(tmpdir):
    # type: (Tempdir) -> None

    scie = tmpdir.join("scie")
    run_pex_command(
        args=["cowsay<6", "-c", "cowsay", "--scie", "eager", "--scie-only", "-o", scie]
    ).assert_success()

    split_dir = tmpdir.join("split")
    subprocess.check_call(args=[scie, split_dir], env=make_env(SCIE="split"))
    subprocess.check_call(
        args=[os.path.join(".", SysPlatform.CURRENT.binary_name("scie-jump"))], cwd=split_dir
    )
    re_packed_scie = os.path.join(split_dir, "scie")
    assert b"| Scie-Moo! |" in subprocess.check_output(args=[re_packed_scie, "Scie-Moo!"])
    assert filecmp.cmp(scie, re_packed_scie, shallow=False)
