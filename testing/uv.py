# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys

import pytest

SKIP_REASON = "Use of uv is required and uv only supports Python >= 3.8."


def is_uv_supported():
    # type: () -> bool
    return sys.version_info >= (3, 8)


mark_skip_if_uv_not_supported = pytest.mark.skipif(not is_uv_supported(), reason=SKIP_REASON)


def skip_if_uv_not_supported():
    # type: () -> None
    if not is_uv_supported():
        pytest.skip(SKIP_REASON)
