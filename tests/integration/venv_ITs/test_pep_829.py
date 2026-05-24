# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import sys

from testing import make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_pex_extra_sys_path(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    debug_file = tmpdir.join("debug.json")
    one = tmpdir.join("entry-one")
    two = tmpdir.join("entry-two")
    three = tmpdir.join("entry-three")
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--venv",
            "--",
            "-c",
            "import json, sys; json.dump(sys.path, sys.stdout)",
        ],
        env=make_env(
            PEX_EXTRA_SYS_PATH=os.pathsep.join([two, one]),
            __PEX_EXTRA_SYS_PATH__=three,
            __PEX_EXTRA_SYS_PATH_DEBUG__=debug_file,
        ),
    )
    result.assert_success()

    observed_sys_path = json.loads(result.output)
    assert [two, one, three] == observed_sys_path[-3:]

    with open(debug_file) as fp:
        data = json.load(fp)

    assert data["legacy"] == (sys.version_info[:2] < (3, 15))
    assert [two, one, three] == data["entries"]
