# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.pip.version import PipVersion

skip_if_only_vendored_pip_supported = pytest.mark.skipif(
    PipVersion.LATEST_COMPATIBLE is PipVersion.VENDORED, reason="This test requires `pip>=22.2.2`."
)
