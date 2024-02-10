# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import subprocess

import pytest

from pex.common import temporary_dir
from pex.pip.installation import get_pip
from pex.resolve.configured_resolver import ConfiguredResolver
from testing import IS_LINUX_ARM64, IS_PYPY, PY_VER, run_pex_command


@pytest.mark.skipif(
    IS_LINUX_ARM64 or IS_PYPY or PY_VER > (3, 10),
    reason=(
        "The cryptography 2.6.1 project only has pre-built wheels for CPython <= 3.10 for some "
        "platforms available on PyPI and this test relies upon a pre-built wheel being available."
    ),
)
def test_abi3_resolution():
    # type: () -> None
    # The cryptography team releases the following relevant pre-built wheels for version 2.6.1:
    # cryptography-2.6.1-cp27-cp27m-macosx_10_6_intel.whl
    # cryptography-2.6.1-cp27-cp27m-manylinux1_x86_64.whl
    # cryptography-2.6.1-cp27-cp27mu-manylinux1_x86_64.whl
    # cryptography-2.6.1-cp34-abi3-macosx_10_6_intel.whl
    # cryptography-2.6.1-cp34-abi3-manylinux1_x86_64.whl
    # With pex in --no-build mode, we force a test that pex abi3 resolution works when this test is
    # run under CPython>3.4,<3.11 on OSX and linux.

    with temporary_dir() as td:
        # The dependency graph for cryptography-2.6.1 includes pycparser which is only released as an
        # sdist. Since we want to test in --no-build, we pre-resolve/build the pycparser wheel here and
        # add the resulting wheelhouse to the --no-build pex command.
        download_dir = os.path.join(td, ".downloads")
        pip = get_pip(resolver=ConfiguredResolver.default())
        pip.spawn_download_distributions(
            download_dir=download_dir, requirements=["pycparser"]
        ).wait()
        wheel_dir = os.path.join(td, ".wheels")
        pip.spawn_build_wheels(
            wheel_dir=wheel_dir, distributions=glob.glob(os.path.join(download_dir, "*"))
        ).wait()

        cryptography_pex = os.path.join(td, "cryptography.pex")
        res = run_pex_command(
            ["-f", wheel_dir, "--no-build", "cryptography==2.6.1", "-o", cryptography_pex]
        )
        res.assert_success()

        subprocess.check_call([cryptography_pex, "-c", "import cryptography"])
