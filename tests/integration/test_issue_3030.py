# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess

from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_venv_symlinks_data_top_level_matches_wheel_package(
    tmpdir,  # type: Tempdir
    py311,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "databricks-connect==15.4.0",
            "--venv",
            "-o",
            pex,
        ],
        python=py311.binary,
    ).assert_success()

    assert pex_root == commonpath(
        (
            pex_root,
            subprocess.check_output(
                args=[py311.binary, pex, "-c", "import pyspark; print(pyspark.__file__)"]
            )
            .decode("utf-8")
            .strip(),
        )
    )
