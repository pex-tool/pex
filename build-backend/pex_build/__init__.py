# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

# When running under MyPy, this will be set to True for us automatically; so we can use it as a
# typing module import guard to protect Python 2 imports of typing - which is not normally available
# in Python 2.
TYPE_CHECKING = False


INCLUDE_DOCS = os.environ.get("__PEX_BUILD_INCLUDE_DOCS__", "False").lower() in ("1", "true")
