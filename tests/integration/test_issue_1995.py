# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

import pytest

from pex.typing import TYPE_CHECKING
from testing import IS_LINUX, PY310, ensure_python_interpreter, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(not IS_LINUX, reason="We only release from Linux in CI.")
def test_packaging(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None
    pex = os.path.join(str(tmpdir), "pex.pex")
    package_script = os.path.join(pex_project_dir, "scripts", "create-packages.py")
    run_pex_command(
        args=[
            "toml",
            pex_project_dir,
            "--",
            package_script,
            "-v",
            "--pex-output-file",
            pex,
        ],
        # The package script requires Python>=3.8.
        python=(
            sys.executable if sys.version_info[:2] >= (3, 8) else ensure_python_interpreter(PY310)
        ),
    ).assert_success()
    assert os.path.exists(pex), "Expected {pex} to be created by {package_script}.".format(
        pex=pex, package_script=package_script
    )
    # The packaged Pex PEX should work with all Pythons we support, including the current test
    # interpreter.
    subprocess.check_call(args=[sys.executable, pex, "-V"], env=make_env(PEX_PYTHON=sys.executable))
