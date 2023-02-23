# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

import pytest

from pex.cli.testing import run_pex3
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 5),
    reason="The tested distribution is only compatible with Python >= 3.5",
)
def test_build_system_no_build_backend(tmpdir):
    # type: (Any) -> None

    run_pex3("lock", "create", "xmlsec==1.3.13").assert_success()
