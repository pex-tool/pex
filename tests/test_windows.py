# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex import windows
from pex.sysconfig import SysPlatform
from testing.pytest_utils.tmp import Tempdir


def test_is_script(tmpdir):
    # type: (Tempdir) -> None

    assert windows.is_script(
        windows.create_script(
            tmpdir.join("script"), "import sys; sys.exit(0)", SysPlatform.WINDOWS_X86_64
        )
    )
