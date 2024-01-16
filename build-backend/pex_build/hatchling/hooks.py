# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from typing import Type

from hatchling.plugin import hookimpl
from pex_build.hatchling.dynamic_requires_python import DynamicRequiresPythonHook


@hookimpl
def hatch_register_metadata_hook():
    # type: () -> Type[DynamicRequiresPythonHook]
    return DynamicRequiresPythonHook
