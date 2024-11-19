# Copyright 2020 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum


class BinPath(Enum["BinPath.Value"]):
    class Value(Enum.Value):
        pass

    FALSE = Value("false")
    PREPEND = Value("prepend")
    APPEND = Value("append")


BinPath.seal()
