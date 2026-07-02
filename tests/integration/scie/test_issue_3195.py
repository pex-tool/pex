# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import json

from pex.os import Os
from pex.platforms import Platform
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider

if TYPE_CHECKING:
    pass


@skip_if_no_provider
def test_scie_only_foreign_platform(
    tmpdir,  # type: Tempdir
    current_platform,  # type: Platform
):
    # type: (...) -> None

    scie = tmpdir.join("scie")
    nce = tmpdir.join("nce")

    foreign_platform = (
        "macosx_12_0_arm64-cp-3.12.3-cp312"
        if Os.CURRENT is not Os.MACOS
        else "manylinux2014_x86_64-cp-3.12.3-cp312"
    )
    run_pex_command(
        args=[
            "--scie",
            "eager",
            "--scie-only",
            "--scie-base",
            nce,
            "-o",
            scie,
            "--platform",
            foreign_platform,
            "--scie-only",
        ]
    ).assert_success()
    scies = glob.glob(tmpdir.join("scie*"))
    assert len(scies) == 1
    scie = scies[0]

    # N.B.: Prove the scie is a scie and not a PEX by leveraging the fact we build scies using
    # `--single-lift-line` such that the last "line" of the binary is the lift manifest.
    manifest_contents = b""
    with open(scie, "rb") as fp:
        for line in fp:
            manifest_contents = line
    try:
        manifest = json.loads(manifest_contents)
    except ValueError:
        raise AssertionError("The file at {scie} is not a scie.".format(scie=scie))
    else:
        assert "scie" == manifest["scie"]["lift"]["name"]
