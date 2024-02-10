# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

import pytest

from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 7),
    reason="The tested distribution is only compatible with Python >= 3.7",
)
def test_get_requires_for_build_wheel(tmpdir):
    # type: (Any) -> None

    run_pex3("lock", "create", "cairocffi==1.5.1").assert_success()
