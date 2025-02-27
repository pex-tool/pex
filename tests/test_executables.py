# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os
from typing import Optional

import pytest

from pex.common import touch
from pex.executables import chmod_plus_x, is_python_script, is_script
from pex.os import WINDOWS, is_exe
from pex.pep_427 import install_wheel_interpreter
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(WINDOWS, reason="This test checks posix expectations of a script.")
def test_is_script_posix(tmpdir):
    # type: (Tempdir) -> None

    exe = tmpdir.join("exe")

    touch(exe)
    assert not is_exe(exe)
    assert not is_script(exe, pattern=None, check_executable=True)

    chmod_plus_x(exe)
    assert is_exe(exe)
    assert not is_script(exe, pattern=None, check_executable=True)

    with open(exe, "wb") as fp:
        fp.write(bytearray([0xCA, 0xFE, 0xBA, 0xBE]))
    assert not is_script(fp.name, pattern=None, check_executable=True)

    with open(exe, "wb") as fp:
        fp.write(b"#!/mystery\n")
        fp.write(bytearray([0xCA, 0xFE, 0xBA, 0xBE]))
    assert is_script(exe, pattern=None, check_executable=True)
    assert is_script(exe, pattern=br"^/mystery", check_executable=True)
    assert not is_script(exe, pattern=br"^python", check_executable=True)

    os.chmod(exe, 0o665)
    assert is_script(exe, pattern=None, check_executable=False)
    assert not is_script(exe, pattern=None, check_executable=True)
    assert not is_exe(exe)


def test_is_python_script(tmpdir):
    # type: (Tempdir) -> None

    exe = tmpdir.join("exe")

    touch(exe)
    assert not is_python_script(exe, check_executable=False)
    assert not is_python_script(exe, check_executable=True)

    def write_shebang(shebang):
        # type: (str) -> None
        with open(exe, "w") as fp:
            fp.write(shebang)

    write_shebang("#!python")
    assert is_python_script(exe, check_executable=False)
    assert not is_python_script(exe, check_executable=True)

    def check_is_python_script(shebang=None):
        # type: (Optional[str]) -> None
        if shebang:
            write_shebang(shebang)
        assert is_python_script(exe, check_executable=not WINDOWS)

    chmod_plus_x(exe)

    check_is_python_script()
    check_is_python_script("#!/usr/bin/python")
    check_is_python_script("#!/usr/bin/python3")
    check_is_python_script("#!/usr/bin/python3.13")
    check_is_python_script("#!/usr/bin/python -sE")
    check_is_python_script("#!/usr/bin/env python")
    check_is_python_script("#!/usr/bin/env python2.7")
    check_is_python_script("#!/usr/bin/env python -sE")
    check_is_python_script("#!/usr/bin/env -S python")
    check_is_python_script("#!/usr/bin/env -S python3")
    check_is_python_script("#!/usr/bin/env -S python -sE")


def test_pip_console_script_is_python_script(tmpdir):
    # type: (Tempdir) -> None

    venv = Virtualenv.create(
        tmpdir.join("venv"), install_pip=InstallationChoice.YES, other_installs=["cowsay"]
    )
    for script_name in "pip", "cowsay":
        script_path = venv.bin_path(script_name)
        assert is_python_script(
            script_path
        ), "Expected {script} to be considered a Python script.".format(script=script_path)


def test_pex_console_script_is_python_script(tmpdir):
    # type: (Tempdir) -> None

    venv = Virtualenv.create(tmpdir.join("venv"), install_pip=InstallationChoice.YES)

    wheel_dir = tmpdir.join("wheels")
    venv.interpreter.execute(args=["-m", "pip", "wheel", "cowsay", "--wheel-dir", wheel_dir])

    wheels = glob.glob(os.path.join(wheel_dir, "cowsay*.whl"))
    assert 1 == len(wheels)
    cowsay_wheel = wheels[0]

    install_wheel_interpreter(cowsay_wheel, venv.interpreter)

    for script_name in "pip", "cowsay":
        script_path = venv.bin_path(script_name)
        assert is_python_script(
            script_path
        ), "Expected {script} to be considered a Python script.".format(script=script_path)
