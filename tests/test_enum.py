# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import re

import pytest

from pex.common import qualified_name
from pex.enum import Enum


class Color(Enum["Color.Value"]):
    class Value(Enum.Value):
        pass

    RED = Value("red")
    GREEN = Value("green")
    BLUE = Value("blue")


def test_basics():
    # type: () -> None

    assert Color.RED is Color.for_value("red")
    assert Color.RED == Color.for_value("red")

    assert Color.GREEN is not Enum.Value("green")
    assert Color.GREEN != Enum.Value("green")

    assert Color.BLUE is not Color.Value("blue")
    assert Color.BLUE != Color.Value("blue")

    assert Color.for_value("red") is not Color.for_value("green") is not Color.for_value("blue")
    assert Color.for_value("red") != Color.for_value("green") != Color.for_value("blue")

    with pytest.raises(ValueError):
        Color.for_value("yellow")


def test_value():
    # type: () -> None

    assert ["red", "green", "blue"] == [color.value for color in Color.values()]


def test_ordinal():
    # type: () -> None

    assert [0, 1, 2] == [color.ordinal for color in Color.values()]

    class PlaceHolder(Enum["PlaceHolder.Value"]):
        class Value(Enum.Value):
            pass

        FOO = Value("foo")
        BAR = Value("bar")
        BAZ = Value("baz")

    assert [0, 1, 2] == [place_holder.ordinal for place_holder in PlaceHolder.values()]


def test_comparable():
    # type: () -> None

    assert Color.BLUE > Color.RED
    assert Color.GREEN >= Color.RED
    assert Color.RED >= Color.RED
    assert Color.RED <= Color.RED
    assert Color.RED < Color.GREEN

    assert [Color.RED, Color.GREEN, Color.BLUE] == sorted(Color.values())
    assert [Color.RED, Color.GREEN, Color.BLUE] == sorted([Color.GREEN, Color.RED, Color.BLUE])

    class Op(Enum["Op.Value"]):
        class Value(Enum.Value):
            pass

        ADD = Value("+")
        SUB = Value("-")

    with pytest.raises(
        TypeError,
        match=re.escape(
            "Can only compare values of type {op_value_type} amongst themselves; given 'red' of "
            "type {color_value_type}.".format(
                op_value_type=qualified_name(Op.Value),
                color_value_type=qualified_name(Color.Value),
            )
        ),
    ):
        assert Op.SUB > Color.RED
