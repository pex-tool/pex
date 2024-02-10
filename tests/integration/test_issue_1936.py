# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess

from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_empty_pex_path(tmpdir):
    # type: (Any) -> None

    empty_pex = os.path.join(str(tmpdir), "empty.pex")
    run_pex_command(args=["-o", empty_pex]).assert_success()

    # The previously failing case.
    subprocess.check_call(args=[empty_pex, "-c", ""], env=make_env(PEX_PATH=""))

    colors_pex = os.path.join(str(tmpdir), "colors.pex")
    run_pex_command(
        args=["ansicolors==1.1.8", "-o", colors_pex, "--layout", "packed"]
    ).assert_success()

    assert 0 != subprocess.call(
        args=[empty_pex, "-c", "import colors"]
    ), "Expected a PEX_PATH including colors.pex to be needed in order to import colors."
    subprocess.check_call(
        args=[empty_pex, "-c", "import colors"], env=make_env(PEX_PATH=colors_pex)
    )
    # Demonstrate that . can be used instead of the empty string to trigger a CWD PEX_PATH if that
    # is what is intended.
    subprocess.check_call(
        args=[empty_pex, "-c", "import colors"], env=make_env(PEX_PATH="."), cwd=colors_pex
    )
