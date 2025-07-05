# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.scie import Provider
from pex.sysconfig import SysPlatform
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER

if TYPE_CHECKING:
    from typing import Optional


def provider():
    # type: () -> Optional[Provider.Value]
    if IS_PYPY:
        if PY_VER == (2, 7):
            return Provider.PyPy

        if SysPlatform.LINUX_AARCH64 is SysPlatform.CURRENT and PY_VER >= (3, 7):
            return Provider.PyPy
        elif SysPlatform.MACOS_AARCH64 is SysPlatform.CURRENT and PY_VER >= (3, 8):
            return Provider.PyPy
        elif PY_VER >= (3, 6):
            return Provider.PyPy
        else:
            return None
    elif (3, 9) <= PY_VER < (3, 14):
        return Provider.PythonBuildStandalone
    else:
        return None


def has_provider():
    # type: () -> bool
    return provider() is not None


skip_if_no_provider = pytest.mark.skipif(
    not has_provider(),
    reason=(
        "Either A PBS or PyPy release must be available for the current interpreter to run this "
        "test."
    ),
)
