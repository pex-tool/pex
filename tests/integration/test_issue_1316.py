# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys

import pytest

from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(sys.version_info[:2] < (3, 6), reason="PyYAML 6.0.1 requires Python >= 3.6")
def test_resolve_cyclic_dependency_graph(tmpdir):
    # type: (Any) -> None
    naked_pex = os.path.join(str(tmpdir), "naked.pex")

    # N.B.: Naked 0.1.31 requires PyYAML unbounded and old versions of PyYAML that work with Python
    # 2.7 have been broken by the Cython 3.0.0 release. As such we exclude older versions of Python
    # from this test and pin PyYAML to a newer version that works with Cython>=3.
    constraints = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints, "w") as fp:
        fp.write("PyYAML==6.0.1")

    run_pex_command(
        args=["Naked==0.1.31", "--constraints", constraints, "-o", naked_pex]
    ).assert_success()
    subprocess.check_call(args=[naked_pex, "-c", "import Naked"])
