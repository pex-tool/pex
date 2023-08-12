# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
from textwrap import dedent

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_long_wheel_names(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "pycryptodome==3.16.0",
            "--",
            "-c",
            dedent(
                """\
                import json
                import sys

                import Crypto


                json.dump({"version": Crypto.__version__, "path": Crypto.__file__}, sys.stdout)
                """
            ),
        ]
    )
    result.assert_success()
    data = json.loads(result.output)
    assert "3.16.0" == data["version"]
    assert pex_root == commonpath((pex_root, data["path"]))
