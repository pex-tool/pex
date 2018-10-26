# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

__version__ = '1.5.1'

SETUPTOOLS_REQUIREMENT = 'setuptools==40.4.3'

# We're currently stuck here due to removal of an API we depend on.
# See: https://github.com/pantsbuild/pex/issues/603
WHEEL_REQUIREMENT = 'wheel==0.31.1'
