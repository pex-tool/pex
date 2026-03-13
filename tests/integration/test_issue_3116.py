# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys

from pex.common import safe_rmtree
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    pass


def test_enum_backport_injection_foiled(tmpdir):
    # type: (Tempdir) -> None

    pythonpath = tmpdir.join("pythonpath")
    run_pex3("venv", "create", "--layout", "flat", "-d", pythonpath, "enum34").assert_success()

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("cowsay.pex")
    run_pex_command(
        args=["--runtime-pex-root", pex_root, "cowsay<6", "-c", "cowsay", "-o", pex]
    ).assert_success()

    assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"])

    safe_rmtree(pex_root)
    assert b"| Boo! |" in subprocess.check_output(args=[sys.executable, pex, "Boo!"])

    safe_rmtree(pex_root)
    assert b"| Foo! |" in subprocess.check_output(
        args=[pex, "Foo!"], env=make_env(PYTHONPATH=pythonpath)
    )

    safe_rmtree(pex_root)
    assert b"| Bar! |" in subprocess.check_output(
        args=[sys.executable, pex, "Bar!"], env=make_env(PYTHONPATH=pythonpath)
    )
