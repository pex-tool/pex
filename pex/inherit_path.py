# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Tuple, Union


class InheritPath(object):
    class Value(object):
        def __init__(self, value):
            # type: (str) -> None
            self.value = value

        def __repr__(self):
            # type: () -> str
            return repr(self.value)

    FALSE = Value("false")
    PREFER = Value("prefer")
    FALLBACK = Value("fallback")

    values = FALSE, PREFER, FALLBACK

    @classmethod
    def for_value(cls, value):
        # type: (Union[str, bool]) -> InheritPath.Value
        if value is False:
            return InheritPath.FALSE
        elif value is True:
            return InheritPath.PREFER
        for v in cls.values:
            if v.value == value:
                return v
        raise ValueError(
            "{!r} of type {} must be one of {}".format(
                value, type(value), ", ".join(map(repr, cls.values))
            )
        )
