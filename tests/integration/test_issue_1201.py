# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.typing import TYPE_CHECKING
from testing import run_pex_command, subprocess

if TYPE_CHECKING:
    from typing import Any


def test_old_requires_metadata_used_for_requires_python(tmpdir):
    # type: (Any) -> None
    pex_file = os.path.join(str(tmpdir), "et-xmlfile.pex")
    result = run_pex_command(args=["et-xmlfile==1.0.1", "-o", pex_file])
    result.assert_success()
    subprocess.check_call(args=[pex_file, "-c", "import et_xmlfile"])
