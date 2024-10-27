# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.scie import SciePlatform
from testing import IS_PYPY, PY_VER


def has_provider():
    # type: () -> bool
    if IS_PYPY:
        if PY_VER == (2, 7):
            return True

        if SciePlatform.LINUX_AARCH64 is SciePlatform.CURRENT:
            return PY_VER >= (3, 7)
        elif SciePlatform.MACOS_AARCH64 is SciePlatform.CURRENT:
            return PY_VER >= (3, 8)
        else:
            return PY_VER >= (3, 6)
    else:
        return (3, 9) <= PY_VER < (3, 14)


skip_if_no_provider = pytest.mark.skipif(
    not has_provider(),
    reason=(
        "Either A PBS or PyPy release must be available for the current interpreter to run this "
        "test."
    ),
)
