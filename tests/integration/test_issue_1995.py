# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_packaging(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None
    pex = os.path.join(str(tmpdir), "pex.pex")
    package_script = os.path.join(pex_project_dir, "scripts", "package.py")
    run_pex_command(
        args=[
            "toml",
            pex_project_dir,
            "--",
            package_script,
            "-v",
            "--pex-output-file",
            pex,
        ]
    ).assert_success()
    assert os.path.exists(pex), "Expected {pex} to be created by {package_script}.".format(
        pex=pex, package_script=package_script
    )
    subprocess.check_call(args=[sys.executable, pex, "-V"], env=make_env(PEX_PYTHON=sys.executable))
