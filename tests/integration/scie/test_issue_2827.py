# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import subprocess

from pex.cache.dirs import CacheDir
from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider

if TYPE_CHECKING:
    from typing import Optional


def assert_scie_base(
    scie,  # type: str
    expected_base=None,  # type: Optional[str]
):
    manifest = json.loads(subprocess.check_output(args=[scie], env=make_env(SCIE="inspect")))
    actual_base = manifest["scie"]["lift"].get("base", None)
    if actual_base is None:
        assert expected_base is None
        return

    assert expected_base == actual_base
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

    expected_scie_base = CacheDir.SCIES.path("base", pex_root=pex_root)
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


@skip_if_no_provider
def test_issue_2864(tmpdir):
    # type: (Tempdir) -> None

    scie = tmpdir.join("scie")
    run_pex_command(args=["--scie", "eager", "--scie-only", "-o", scie]).assert_success()
    assert_scie_base(scie)
