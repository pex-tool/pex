# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

import pytest
from _pytest.monkeypatch import MonkeyPatch

from pex.common import safe_mkdir, safe_rmtree
from pex.compatibility import commonpath
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.fixture
def fake_system_tmp_dir(
    tmpdir,  # type: Tempdir
    monkeypatch,  # type: MonkeyPatch
):
    # type: (...) -> str

    fake_system_tmp_dir = safe_mkdir(tmpdir.join("tmp"))
    monkeypatch.setenv("TMPDIR", fake_system_tmp_dir)

    tmpdir_path = (
        subprocess.check_output(
            args=[sys.executable, "-c", "import tempfile; print(tempfile.mkdtemp())"]
        )
        .decode("utf-8")
        .strip()
    )
    safe_rmtree(tmpdir_path)
    assert fake_system_tmp_dir == commonpath((fake_system_tmp_dir, tmpdir_path))

    return fake_system_tmp_dir


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
