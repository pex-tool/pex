# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

import pytest

from pex.common import temporary_dir
from pex.testing import IS_PYPY, run_pex_command


@pytest.mark.skipif(
    IS_PYPY,
    reason="On PyPy this causes this error: Failed to execute PEX file. Needed "
    "manylinux2014_x86_64-pp-272-pypy_41 compatible dependencies for 1: "
    "cryptography==2.5 But this pex only contains "
    "cryptography-2.5-pp27-pypy_41-linux_x86_64.whl. "
    "Temporarily skipping the test on PyPy allows us to get tests passing "
    "again, until we can address this.",
)
def test_devendoring_required():
    # type: () -> None
    # The cryptography distribution does not have a whl released for python3 on linux at version 2.5.
    # As a result, we're forced to build it under python3 and, prior to the fix for
    # https://github.com/pantsbuild/pex/issues/661, this would fail using the vendored setuptools
    # inside pex.
    with temporary_dir() as td:
        cryptography_pex = os.path.join(td, "cryptography.pex")
        res = run_pex_command(["cryptography==2.5", "-o", cryptography_pex])
        res.assert_success()

        subprocess.check_call([cryptography_pex, "-c", "import cryptography"])
