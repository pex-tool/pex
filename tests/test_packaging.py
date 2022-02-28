# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

from pex.interpreter import PythonInterpreter
from pex.testing import make_env
from pex.tools.commands import all_commands
from pex.venv.virtualenv import Virtualenv
from pex.version import __version__

# N.B.: Our test environments include Pex installed from our pyproject.toml in a Tox managed venv.
# This is how Tox works and its critical background to the assumptions made in the tests below.


def test_expected_scripts():
    # type: () -> None
    interpreter = PythonInterpreter.get()
    assert interpreter.is_venv
    assert {"pex", "pex-tools"}.issubset(
        os.path.basename(exe) for exe in Virtualenv(interpreter.prefix).iter_executables()
    )


def script_path(script_name):
    # type: (str) -> str
    return os.path.join(os.path.dirname(sys.executable), script_name)


def test_pex_script():
    # type: () -> None
    output = subprocess.check_output(
        args=[script_path("pex"), "--version"],
        # On Python 2.7 --version gets printed to stderr.
        stderr=subprocess.STDOUT,
    )
    assert __version__ == output.decode("utf-8").strip()


def test_pex_tools_script():
    # type: () -> None
    command_names = ",".join([command_type.name() for command_type in all_commands()])
    expected_first_line = (
        "usage: pex-tools [-h] [-V] [-v] [--emit-warnings] [--pex-root PEX_ROOT] [--disable-cache] "
        "[--cache-dir CACHE_DIR] [--tmpdir TMPDIR] [--rcfile RC_FILE] PATH "
        "{{{command_names}}} ...".format(command_names=command_names)
    )

    # Make sure we don't word-wrap for simplicity of testing.
    env = make_env(COLUMNS=len(expected_first_line) + 2)

    output = subprocess.check_output(args=[script_path("pex-tools"), "-h"], env=env)
    first_line = output.decode("utf-8").splitlines()[0]
    assert expected_first_line == first_line, output.decode("utf-8")
