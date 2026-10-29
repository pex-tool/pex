# Copyright 2020 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Union


class InheritPath(Enum["InheritPath.Value"]):
    class Value(Enum.Value):
        pass

    FALSE = Value("false")
    PREFER = Value("prefer")
    FALLBACK = Value("fallback")

    @classmethod
    def for_value(cls, value):
        # type: (Union[str, bool]) -> InheritPath.Value
        if isinstance(value, str):
            return super(InheritPath, cls).for_value(value)
        elif value:
            return InheritPath.PREFER
        else:
            return InheritPath.FALSE


InheritPath.seal()
