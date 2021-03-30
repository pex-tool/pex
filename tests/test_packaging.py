# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

from pex.interpreter import PythonInterpreter
from pex.tools.commands import all_commands
from pex.tools.commands.virtualenv import Virtualenv
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
    command_names = ",".join([command.__class__.__name__.lower() for command in all_commands()])

    output = subprocess.check_output(args=[script_path("pex-tools"), "-h"])
    first_line = output.decode("utf-8").splitlines()[0]
    assert (
        "usage: pex-tools [-h] [-V] PATH {{{command_names}}} ...".format(
            command_names=command_names
        )
        == first_line
    )
