# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys

import pytest

from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 7) or sys.version_info[:2] >= (3, 10),
    reason="Pants 2.12.0.dev3 requires Python >=3.7,<3.10",
)
def test_check_install_issue_1730(
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex_args = [
        "--pex-root",
        pex_root,
        "--runtime-pex-root",
        pex_root,
        "pantsbuild.pants.testutil==2.12.0.dev3",
        "--",
        "-c",
        "from pants import testutil; print(testutil.__file__)",
    ]

    old_result = run_pex_command(args=["pex==2.1.81", "-c", "pex", "--"] + pex_args, quiet=True)
    old_result.assert_failure()
    assert (
        "Failed to resolve compatible distributions:\n"
        "1: pantsbuild.pants.testutil==2.12.0.dev3 requires pantsbuild.pants==2.12.0.dev3 but "
        "pantsbuild.pants 2.12.0.dev3 was resolved" in old_result.error
    ), old_result.error

    new_result = run_pex_command(args=pex_args, quiet=True)
    new_result.assert_success()
    assert new_result.output.startswith(pex_root)
