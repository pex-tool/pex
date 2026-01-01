# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys

import pytest

from pex.common import safe_mkdir
from testing import PY27, PY311, ensure_python_interpreter, run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 12),
    reason="Vendored Pip bootstrapping only occurs when using Pex installed via a Python 3.12+ whl.",
)
@pytest.mark.parametrize(
    "old_python",
    [
        pytest.param(ensure_python_interpreter(version), id="py" + version)
        for version in (PY27, PY311)
    ],
)
def test_bootstrap_vendored_pip(
    tmpdir,  # type: Tempdir
    old_python,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("cowsay.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--python",
            old_python,
            "--pip-version",
            "vendored",
            "--no-allow-pip-version-fallback",
            "cowsay<6",
            "-c",
            "cowsay",
            "-o",
            pex,
        ],
        use_pex_whl_venv=True,
        # N.B.: This ensures we don't pick up vendored Pip from the default CWD of the Pex repo
        # root.
        cwd=safe_mkdir(tmpdir.join("empty-pythonpath")),
    ).assert_success()
    assert b"| Moo! |" in subprocess.check_output(args=[old_python, pex, "Moo!"])
