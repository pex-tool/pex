# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.common import touch
from pex.executables import chmod_plus_x, is_python_script, is_script
from pex.os import is_exe
from testing.pytest.tmp import Tempdir


def test_is_script(tmpdir):
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

    chmod_plus_x(exe)
    assert is_python_script(exe, check_executable=True)

    write_shebang("#!/usr/bin/python")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/python3")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/python3.13")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/python -sE")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/env python")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/env python2.7")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/env python -sE")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/env -S python")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/env -S python3")
    assert is_python_script(exe)

    write_shebang("#!/usr/bin/env -S python -sE")
    assert is_python_script(exe)
