# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pex_build
from hatchling.plugin import hookimpl
from pex_build.hatchling.build_hook import AdjustBuild
from pex_build.hatchling.metadata_hook import AdjustMetadata

if pex_build.TYPE_CHECKING:
    from typing import Type


@hookimpl
def hatch_register_metadata_hook():
    # type: () -> Type[AdjustMetadata]
    return AdjustMetadata


@hookimpl
def hatch_register_build_hook():
    # type: () -> Type[AdjustBuild]
    return AdjustBuild
