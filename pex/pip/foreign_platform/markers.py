# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os


def patch():
    from pip._vendor.packaging import markers  # type: ignore[import]

    # N.B.: The following environment variable is used by the Pex runtime to control Pip and must be
    # kept in-sync with `__init__.py`.
    patched_markers_file = os.environ.pop("_PEX_PATCHED_MARKERS_FILE")
    with open(patched_markers_file) as fp:
        patched_markers = json.load(fp)

    markers.default_environment = patched_markers.copy
