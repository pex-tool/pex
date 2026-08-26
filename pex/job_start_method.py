# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum


class StartMethod(Enum["StartMethod.Value"]):
    class Value(Enum.Value):
        pass

    FORK = Value("fork")
    FORKSERVER = Value("forkserver")
    SPAWN = Value("spawn")


StartMethod.seal()
