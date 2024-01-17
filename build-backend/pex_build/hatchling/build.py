# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

# We re-export all hatchling's PEP-517 build backend hooks here for the build frontend to call.
from hatchling.build import *  # NOQA
