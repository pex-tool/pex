# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys

import pytest

# Utilities related to Pex Python PI support bring-up.
# These will all be removed as tracked by https://github.com/pex-tool/pex/issues/2564

skip_flit_core_39 = pytest.mark.skipif(
    sys.version_info[:2] >= (3, 14),
    reason=(
        "As of its latest 3.9.0 release, flit_core relies on ast.Str which was removed in Python "
        "3.14. This was fixed in"
        "https://github.com/pypa/flit/commit/6ab62c91d0db451b5e9ab000f0dba5471550b442 and will be "
        "released in 3.10 at which point this skip can be removed."
    ),
)
