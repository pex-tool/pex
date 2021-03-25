# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""The PEX packaging toolchain."""  # N.B.: Flit uses this as our distribution description.

from __future__ import absolute_import

from .version import __version__ as __pex_version__

__version__ = __pex_version__  # N.B.: Flit uses this as out distribution version.
