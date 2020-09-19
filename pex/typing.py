from __future__ import absolute_import

# mypy: implicit-reexport
try:
    from typing import *  # vendor:skip
except ImportError:
    from pex.third_party.typing import *
