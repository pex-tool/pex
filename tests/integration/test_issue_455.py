# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys

import pytest

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import IS_MAC, PY310, ensure_python_venv, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 6),
    reason="The doit 0.34.2 distribution requires at least Python 3.6.",
)
def test_exclude(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--platform",
            "macosx_10.12-x86_64-cp-310-cp310",
            "--platform",
            "linux-x86_64-cp-310-cp310",
            "doit==0.34.2",
            "--exclude",
            "MacFSEvents",
            "--exclude",
            "pyinotify",
            "-c",
            "doit",
            "-o",
            pex,
            "--preserve-pip-download-log",
        ]
    ).assert_success()

    env = os.environ.copy()
    python, pip = ensure_python_venv(PY310)
    subprocess.check_call(args=[pip, "install", "MacFSEvents" if IS_MAC else "pyinotify"])
    env["PEX_INHERIT_PATH"] = "fallback"

    assert (
        b"0.34.2"
        == subprocess.check_output(args=[python, pex, "--version"], env=env).splitlines()[0]
    )

    venv = Virtualenv.enclosing(python)
    assert venv is not None
    env["PEX_INTERPRETER"] = "1"
    module_path = os.path.realpath(
        subprocess.check_output(
            args=[
                python,
                pex,
                "-c",
                "import {excluded_module}; print({excluded_module}.__file__)".format(
                    excluded_module="fsevents" if IS_MAC else "pyinotify"
                ),
            ],
            env=env,
        )
        .decode("utf=8")
        .strip()
    )
    assert venv.site_packages_dir == commonpath((venv.site_packages_dir, module_path)), module_path
