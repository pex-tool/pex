# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

__version__ = '1.1.20'

PACKAGING_REQUIREMENT = 'packaging>=16.8'

# NB: We exlude 7.0b1 since it will use `packaging` if present and we install a modern version of
# packaging that may not be compatible. Versions before 7.0b1 don't use `packaging` and versions
# after use a vendored `packaging`.
SETUPTOOLS_REQUIREMENT = 'setuptools>=5.7,!=7.0b1<31.0'

WHEEL_REQUIREMENT = 'wheel>=0.26.0,<0.30.0'
