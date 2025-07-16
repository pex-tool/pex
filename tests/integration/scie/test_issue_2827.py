# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os.path
import subprocess

from pex.compatibility import commonpath
from testing import make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider


def assert_scie_base(scie, expected_base):
    manifest = json.loads(subprocess.check_output(args=[scie], env=make_env(SCIE="inspect")))
    assert expected_base == manifest["scie"]["lift"]["base"]

    assert expected_base == commonpath(
        (
            expected_base,
            subprocess.check_output(args=[scie, "-c", "import sys; print(sys.executable)"])
            .decode("utf-8")
            .strip(),
        )
    )


@skip_if_no_provider
def test_custom_base(tmpdir):
    # type: (Tempdir) -> None

    scie = tmpdir.join("scie")
    nce = tmpdir.join("nce")
    run_pex_command(
        args=["--scie", "eager", "--scie-only", "--scie-base", nce, "-o", scie]
    ).assert_success()

    assert_scie_base(scie, nce)


@skip_if_no_provider
def test_runtime_pex_root(tmpdir):
    # type: (Tempdir) -> None

    scie = tmpdir.join("scie")
    pex_root = tmpdir.join("pex_root")
    run_pex_command(
        args=["--scie", "eager", "--scie-only", "--runtime-pex-root", pex_root, "-o", scie]
    ).assert_success()

    expected_scie_base = os.path.join(pex_root, "scie-base")
    assert_scie_base(scie, expected_scie_base)


@skip_if_no_provider
def test_custom_base_trumps(tmpdir):
    # type: (Tempdir) -> None

    scie = tmpdir.join("scie")
    nce = tmpdir.join("nce")
    pex_root = tmpdir.join("pex_root")
    run_pex_command(
        args=[
            "--scie",
            "eager",
            "--scie-only",
            "--scie-base",
            nce,
            "--runtime-pex-root",
            pex_root,
            "-o",
            scie,
        ]
    ).assert_success()

    assert_scie_base(scie, nce)
