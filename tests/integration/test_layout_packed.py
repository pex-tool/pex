# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os.path
import subprocess
import sys
import zipfile

from pex.common import open_zip
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_compression(tmpdir):
    # type: (Tempdir) -> None

    def assert_compression(pex, expected_compress_type):
        with open_zip(os.path.join(pex, ".bootstrap")) as zfp:
            assert expected_compress_type == zfp.getinfo("pex/version.py").compress_type
        wheels = glob.glob(os.path.join(pex, ".deps", "*.whl"))
        assert 1 == len(wheels)
        with open_zip(wheels[0]) as zfp:
            assert expected_compress_type == zfp.getinfo("cowsay/characters.py").compress_type

    pex_root = tmpdir.join("pex-root")

    stored_pex = tmpdir.join("stored.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "cowsay==5.0",
            "-c",
            "cowsay",
            "--layout",
            "packed",
            "--no-compress",
            "-o",
            stored_pex,
        ]
    ).assert_success()
    assert_compression(stored_pex, expected_compress_type=zipfile.ZIP_STORED)

    deflated_pex = tmpdir.join("deflated.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "cowsay==5.0",
            "-c",
            "cowsay",
            "--layout",
            "packed",
            "-o",
            deflated_pex,
        ]
    ).assert_success()
    assert_compression(deflated_pex, expected_compress_type=zipfile.ZIP_DEFLATED)

    assert b"| Mo? |" in subprocess.check_output(args=[sys.executable, deflated_pex, "Mo?"])
    assert b"| Mooo! |" in subprocess.check_output(args=[sys.executable, stored_pex, "Mooo!"])
