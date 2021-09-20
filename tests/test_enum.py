# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable


def test_basics():
    # type: () -> None

    class Colors(Enum["Colors.Value"]):
        class Value(Enum.Value):
            pass

        RED = Value("red")
        GREEN = Value("green")
        BLUE = Value("blue")

        @classmethod
        def values(cls):
            # type: () -> Iterable[Colors.Value]
            return cls.RED, cls.GREEN, cls.BLUE

    assert Colors.RED is Colors.for_value("red")
    assert Colors.RED == Colors.for_value("red")

    assert Colors.GREEN is not Enum.Value("green")
    assert Colors.GREEN != Enum.Value("green")

    assert Colors.BLUE is not Colors.Value("blue")
    assert Colors.BLUE != Colors.Value("blue")

    assert Colors.for_value("red") is not Colors.for_value("green") is not Colors.for_value("blue")
    assert Colors.for_value("red") != Colors.for_value("green") != Colors.for_value("blue")

    with pytest.raises(ValueError):
        Colors.for_value("yellow")
