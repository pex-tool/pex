# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

__version__ = '1.4.5'

# Versions 34.0.0 through 35.0.2 (last pre-36.0.0) de-vendored dependencies which causes problems
# for pex code so we exclude that range.
__exclusions = '!=34.*,!=35.*'
SETUPTOOLS_REQUIREMENT = 'setuptools>=20.3,<41,{exclusions}'.format(exclusions=__exclusions)
del __exclusions

WHEEL_REQUIREMENT = 'wheel>=0.26.0,<0.32'
