# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING
from testing import PY310, ensure_python_interpreter, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_pip_leak(tmpdir):
    # type: (Any) -> None
    python = ensure_python_interpreter(PY310)
    pip = os.path.join(os.path.dirname(python), "pip")
    subprocess.check_call(args=[pip, "install", "setuptools_scm==6.0.1"])

    pex_root = os.path.join(str(tmpdir), "pex_root")
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--python",
            python,
            "bitstring==3.1.7",
            "--",
            "-c",
            "import bitstring, os; print(os.path.realpath(bitstring.__file__))",
        ],
        python=python,
    )
    result.assert_success()
    assert os.path.realpath(pex_root) == commonpath(
        [os.path.realpath(pex_root), result.output.strip()]
    )
