from __future__ import absolute_import

# We first try to re-export from the std lib for Python 3. If that fails, we're on Python 2 so used
# the vendored `typing` backport. Note that this backport is specific to Python 2.

# mypy: implicit-reexport
try:
    from typing import *  # vendor:skip
except ImportError:
    from pex.third_party.typing import *
