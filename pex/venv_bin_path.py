# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable


class BinPath(Enum["BinPath.Value"]):
    class Value(Enum.Value):
        pass

    FALSE = Value("false")
    PREPEND = Value("prepend")
    APPEND = Value("append")

    @classmethod
    def values(cls):
        # type: () -> Iterable[BinPath.Value]
        return cls.FALSE, cls.PREPEND, cls.APPEND
