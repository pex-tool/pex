# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import shutil
import sys

from pex.typing import TYPE_CHECKING
from testing import PY39, data, ensure_python_interpreter, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


def test_download_incompatible_python(tmpdir):
    # type: (Any) -> None

    python = ensure_python_interpreter(PY39) if sys.version_info >= (3, 10) else sys.executable

    pex_root = os.path.join(str(tmpdir), "pex_root")
    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "--interpreter-constraint",
        "CPython==3.11.*",
        "pbipy==2.8.2",
        "--indent",
        "2",
        "-o",
        lock,
        python=python,
    ).assert_success()

    complete_platform = data.path("platforms", "complete_platform_linux_x86-64_py311.json")
    pex = os.path.join(str(tmpdir), "pex")
    shutil.rmtree(pex_root)
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--complete-platform",
            complete_platform,
            "pbipy==2.8.2",
            "--lock",
            lock,
            "-o",
            pex,
        ],
        python=python,
    ).assert_success()
