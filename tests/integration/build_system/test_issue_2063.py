# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

import pytest

from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 5) or sys.version_info[:2] >= (3, 12),
    reason=(
        "The tested distribution is only compatible with Python >= 3.5 and it requires lxml (4.9.2)"
        " which only has pre-built wheels available through 3.11."
    ),
)
def test_build_system_no_build_backend(tmpdir):
    # type: (Any) -> None

    run_pex3("lock", "create", "xmlsec==1.3.13").assert_success()
