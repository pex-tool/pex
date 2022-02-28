# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum


class InstallScope(Enum["InstallScope.Value"]):
    class Value(Enum.Value):
        pass

    ALL = Value("all")
    DEPS_ONLY = Value("deps")
    SOURCE_ONLY = Value("srcs")
