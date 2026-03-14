# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
import sys

from pex.common import safe_rmtree
from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    pass


def test_enum_backport_injection_foiled(
    tmpdir,  # type: Tempdir
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None

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

    interpreter = sys.executable
    extra_env = {}
    if 0 != subprocess.call(args=[sys.executable, "-c", ""], env=make_env(PYTHONPATH=pythonpath)):
        # N.B.: Injecting enum34 os the sys.path is so insidious! It can foil Python startup on its
        # own. In particular, when the python interpreter sits in a venv with modern pep-660
        # editables (the Pex test infra case for newer Pythons), those editables `.pth` will fail
        # to load early on interpreter startup. Pex is not in the backtrace there, and we can't help
        # users in that case - Python itself is poisoned. To avoid that case in tests though, we
        # resolve out of our venv interpreter to get the underlying system interpreter with no such
        # editable installs / `.pth` files.
        interpreter = current_interpreter.resolve_base_interpreter().binary
        extra_env = dict(
            PATH=os.pathsep.join((os.path.dirname(interpreter), os.environ.get("PATH", os.defpath)))
        )

    safe_rmtree(pex_root)
    assert b"| Foo! |" in subprocess.check_output(
        args=[pex, "Foo!"], env=make_env(PYTHONPATH=pythonpath, **extra_env)
    )

    safe_rmtree(pex_root)
    assert b"| Bar! |" in subprocess.check_output(
        args=[interpreter, pex, "Bar!"], env=make_env(PYTHONPATH=pythonpath)
    )
