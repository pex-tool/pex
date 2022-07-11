# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from pex.testing import PY310, ensure_python_interpreter, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_pip_leak(tmpdir):
    # type: (Any) -> None
    python = ensure_python_interpreter(PY310)
    pip = os.path.join(os.path.dirname(python), "pip")
    subprocess.check_call(args=[pip, "install", "setuptools_scm==6.0.1"])
    run_pex_command(args=["--python", python, "bitstring==3.1.7"], python=python).assert_success()
