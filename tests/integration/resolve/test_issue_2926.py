# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

import pytest

from pex.compatibility import commonpath
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import IS_LINUX, IS_PYPY, run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    IS_PYPY or sys.version_info[:2] < (3, 7) or not IS_LINUX,
    reason=(
        "The hf-xet 1.1.10 distribution only has wheels available for CPython >= 3.7 and this test "
        "needs wheels with compressed tag sets which are only available for Linux."
    ),
)
def test_bad_wheel_tag_metadata(tmpdir):
    # type: (Tempdir) -> None

    venv = Virtualenv.create(tmpdir.join("venv"), install_pip=InstallationChoice.YES)
    subprocess.check_call(args=[venv.interpreter.binary, "-mpip", "install", "hf-xet==1.1.10"])

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex.packed")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--venv-repository",
            venv.venv_dir,
            "--layout",
            "packed",
            "-o",
            pex,
        ]
    ).assert_success()

    path = (
        subprocess.check_output(
            args=[sys.executable, pex, "-c", "import hf_xet; print(hf_xet.__file__)"]
        )
        .decode("utf-8")
        .strip()
    )
    assert pex_root == commonpath((pex_root, path))

    # N.B.: The original wheel on PyPI is
    # hf_xet-1.1.10-cp37-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl and the WHEEL
    # metadata is:
    # ---
    # Wheel-Version: 1.0
    # Generator: maturin (1.9.4)
    # Root-Is-Purelib: false
    # Tag: cp37-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64
    #
    # That WHEEL metadata should be:
    # ---
    # Wheel-Version: 1.0
    # Generator: maturin (1.9.4)
    # Root-Is-Purelib: false
    # Tag: cp37-abi3-manylinux_2_17_x86_64
    # Tag: cp37-abi3-manylinux2014_x86_64
    #
    # We use packaging.tags.parse_tag on the `cp37-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64`
    # Tag though which handles the compressed tag, but produces a frozenset of
    # `cp37-abi3-manylinux_2_17_x86_64` and `cp37-abi3-manylinux2014_x86_64` which is right, but
    # only up to ordering, which is unstable. We sort the tags to stabilize which results in the
    # `manylinux2014_x86_64` platform tag now coming 1st unlike in the original wheel.
    assert "hf_xet-1.1.10-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl" in path.split(
        os.sep
    )
