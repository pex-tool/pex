# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.compatibility import commonpath
from testing import IS_PYPY, PY_VER, run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    IS_PYPY or PY_VER < (3, 7) or PY_VER >= (3, 14),
    reason=(
        "The ddtrace 2.21.11 distribution requires Python >= 3.7 and only publishes CPython wheels "
        "through Python 3.13."
    ),
)
def test_record_with_non_existent_files(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "ddtrace==2.21.11",
            "--",
            "-c",
            "import ddtrace; print(ddtrace.__file__)",
        ]
    )
    result.assert_success()
    assert pex_root == commonpath((pex_root, result.output.strip()))
