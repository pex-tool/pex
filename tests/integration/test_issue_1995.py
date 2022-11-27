# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

from pex.testing import make_env
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_packaging(tmpdir):
    # type: (Any) -> None
    pex = os.path.join(str(tmpdir), "pex.pex")
    subprocess.check_call(args=["tox", "-e", "package", "--", "--pex-output-file", pex])
    subprocess.check_call(args=[sys.executable, pex, "-V"], env=make_env(PEX_PYTHON=sys.executable))
