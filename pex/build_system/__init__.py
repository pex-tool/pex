# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


# The split of PEP-517 / PEP-518 is quite awkward. PEP-518 doesn't really work without also
# specifying a build backend or knowing a default value for one, but the concept is not defined
# until PEP-517. As such, we break this historical? strange division and define the default outside
# both PEPs.
#
# See: https://peps.python.org/pep-0517/#source-trees
DEFAULT_BUILD_BACKEND = "setuptools.build_meta:__legacy__"
DEFAULT_BUILD_REQUIRES = ("setuptools",)


@attr.s(frozen=True)
class BuildSystemTable(object):
    requires = attr.ib()  # type: Tuple[str, ...]
    build_backend = attr.ib(default=DEFAULT_BUILD_BACKEND)  # type: str
    backend_path = attr.ib(default=())  # type: Tuple[str, ...]


DEFAULT_BUILD_SYSTEM_TABLE = BuildSystemTable(
    requires=DEFAULT_BUILD_REQUIRES, build_backend=DEFAULT_BUILD_BACKEND
)
