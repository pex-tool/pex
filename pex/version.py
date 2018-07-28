# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

__version__ = '1.4.5'

# NB: If we upgrade to setuptools>=34 pex's bootstrap code in `PEXBuilder` will need an update to
# include the `packaging` package in the `.bootstrap/` code since we use
# `packaging.specifiers.SpecifierSet` - indirectly - through `pkg_resources.Requirement.specifier`.
SETUPTOOLS_REQUIREMENT = 'setuptools>=20.3,<34.0'

WHEEL_REQUIREMENT = 'wheel>=0.26.0,<0.32.0'
