# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from pex.common import temporary_dir
from pex.testing import make_env, run_pex_command


def test_force_local_implicit_ns_packages():
    # type: () -> None
    # This was a minimal repro for the issue documented in #598.
    with temporary_dir() as out:
        tcl_pex = os.path.join(out, "tcl.pex")
        run_pex_command(["twitter.common.lang==0.3.9", "-o", tcl_pex])

        subprocess.check_call(
            [tcl_pex, "-c", "from twitter.common.lang import Singleton"],
            env=make_env(PEX_FORCE_LOCAL="1", PEX_PATH=tcl_pex),
        )
