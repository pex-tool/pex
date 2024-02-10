# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import sys

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING
from testing import PY310, ensure_python_interpreter, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


def test_pypy_impl_tag_handling(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.realpath(os.path.join(str(tmpdir), "pex_root"))
    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "lexid",
        "--style",
        "universal",
        "--resolver-version",
        "pip-2020-resolver",
        "--interpreter-constraint",
        ">=3.7,<4",
        "-o",
        lock,
        "--indent",
        "2",
    ).assert_success()

    python = sys.executable if sys.version_info[:2] >= (3, 7) else ensure_python_interpreter(PY310)
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "--",
            "-c",
            "import lexid; print(lexid.__file__)",
        ],
        python=python,
    )
    result.assert_success()
    assert pex_root == commonpath([pex_root, os.path.realpath(result.output.strip())])
