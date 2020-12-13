# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import


class BinPath(object):
    class Value(object):
        def __init__(self, value):
            # type: (str) -> None
            self.value = value

        def __str__(self):
            # type: () -> str
            return str(self.value)

        def __repr__(self):
            # type: () -> str
            return repr(self.value)

    FALSE = Value("false")
    PREPEND = Value("prepend")
    APPEND = Value("append")

    values = FALSE, PREPEND, APPEND

    @classmethod
    def for_value(cls, value):
        # type: (str) -> BinPath.Value
        for v in cls.values:
            if v.value == value:
                return v
        raise ValueError(
            "{!r} of type {} must be one of {}".format(
                value, type(value), ", ".join(map(repr, cls.values))
            )
        )
