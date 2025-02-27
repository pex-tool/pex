# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.common import touch
from pex.executables import chmod_plus_x
from pex.os import is_exe
from testing.pytest_utils.tmp import Tempdir


def test_is_exe(tmpdir):
    # type: (Tempdir) -> None

    all_exe = tmpdir.join("all_exe")
    touch(all_exe)
    chmod_plus_x(all_exe)
    assert is_exe(all_exe)

    other_exe = tmpdir.join("other_exe")
    touch(other_exe)
    os.chmod(other_exe, 0o665)
    assert not is_exe(other_exe)

    not_exe = tmpdir.join("not_exe")
    touch(not_exe)
    assert not is_exe(not_exe)

    exe_dir = tmpdir.join("exe_dir")
    os.mkdir(exe_dir)
    chmod_plus_x(exe_dir)
    assert not is_exe(exe_dir)
