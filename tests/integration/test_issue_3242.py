# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess

from pex.common import open_zip
from pex.sysconfig import SysPlatform
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


def assert_clib_count(
    pex,  # type: str
    expected_count,  # type: int
):
    # type: (...) -> None
    with open_zip(pex) as pex_zip:
        assert expected_count == len(
            [
                name
                for name in pex_zip.namelist()
                if name.startswith("__pex__/.clibs/") and name != "__pex__/.clibs/"
            ]
        )


def get_python_version(pex):
    # type: (str) -> bytes
    return subprocess.check_output(args=[pex, "-c", "import sys; print(sys.version_info)"])


def test_pexrc_platform(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    all_supported_platforms_pex = tmpdir.join("all.pex")
    run_pex_command(
        args=["--runtime-pex-root", pex_root, "--rc", "-o", all_supported_platforms_pex]
    ).assert_success()
    assert_clib_count(all_supported_platforms_pex, len(SysPlatform.values()))
    python_version = get_python_version(all_supported_platforms_pex)

    current_platform_pex = tmpdir.join("current.pex")
    run_pex_command(
        args=[
            "--runtime-pex-root",
            pex_root,
            "--rc",
            "--pexrc-platform",
            SysPlatform.CURRENT.value,
            "-o",
            current_platform_pex,
        ]
    ).assert_success()
    assert_clib_count(current_platform_pex, 1)

    # N.B.: Both PEXes should run identically. The extra pexrc runtimes just go unused on the
    # current platform.
    assert python_version == get_python_version(current_platform_pex)
