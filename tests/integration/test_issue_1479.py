# coding=utf-8
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import platform
import subprocess
import sys

from pex.common import safe_rmtree
from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_unicode_script_shebang_rewrite_docutils(tmpdir):
    # type: (Any) -> None

    # The docutils distribution contains many scripts, one of which, rst2html5.py, contains
    # non-ascii unicode characters which could trip up script shebang re-writing in environments
    # without a default encoding accepting those characters.

    pex_root = os.path.join(str(tmpdir), "pex_root")
    env = make_env(LANG=None, PEX_ROOT=pex_root)

    docutils_pex = os.path.join(str(tmpdir), "docutils.pex")

    run_pex_command(
        args=[
            "docutils==0.17.1",
            "-c",
            "rst2html5.py",
            "-o",
            docutils_pex,
            "--venv",
        ],
        env=env,
    ).assert_success()

    safe_rmtree(pex_root)
    output = subprocess.check_output(args=[docutils_pex, "-V"], env=env)
    assert "rst2html5.py (Docutils 0.17.1 [release], Python {version}, on {platform})\n".format(
        version=platform.python_version(), platform=sys.platform
    ) == output.decode("utf-8")
