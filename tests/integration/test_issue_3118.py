# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys

import pytest

from pex.compatibility import commonpath
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    sys.version_info < (3, 9),
    reason="The ag-ui-protocol 0.1.14 distribution under test requires Python >=3.9.",
)
def test_bad_perms_ignored(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "ag-ui-protocol==0.1.14",
            "--intransitive",
            "--ignore-errors",
            "-o",
            pex,
        ]
    ).assert_success()

    assert pex_root == commonpath(
        (
            pex_root,
            subprocess.check_output(args=[pex, "-c", "import ag_ui; print(ag_ui.__file__)"])
            .decode("utf-8")
            .strip(),
        )
    )
