# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

# The split of PEP-517 / PEP-518 is quite awkward. PEP-518 doesn't really work without also
# specifying a build backend or knowing a default value for one, but the concept is not defined
# until PEP-517. As such, we break this historical? strange division and define the default outside
# both PEPs.
#
# See: https://peps.python.org/pep-0517/#source-trees
DEFAULT_BUILD_BACKEND = "setuptools.build_meta:__legacy__"
