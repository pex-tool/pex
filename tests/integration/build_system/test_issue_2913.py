# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

import pytest

from pex.common import safe_mkdir
from pex.compatibility import commonpath
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8), reason="uv does not work for Python older than 3.8."
)
def test_uv_build_interop(tmpdir):
    # type: (Tempdir) -> None

    project_dir = safe_mkdir(tmpdir.join("uv-pex"))
    subprocess.check_call(args=["uv", "init", "--lib", "--python", sys.executable], cwd=project_dir)

    # N.B.: We place the pylock.toml export in the project directory because uv currently exports
    # the project path as . even when the lock file is exported elsewhere than the project root dir.
    pylock = os.path.join(project_dir, "pylock.toml")
    subprocess.check_call(args=["uv", "export", "--output-file", pylock], cwd=project_dir)

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")
    run_pex_command(
        args=["--pex-root", pex_root, "--runtime-pex-root", pex_root, "--pylock", pylock, "-o", pex]
    ).assert_success()

    assert pex_root == commonpath(
        (
            pex_root,
            subprocess.check_output(args=[pex, "--", "-c", "import uv_pex; print(uv_pex.__file__)"])
            .decode("utf-8")
            .strip(),
        )
    )
