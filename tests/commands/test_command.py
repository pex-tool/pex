# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.commands.command import Error, ResultError, catch, try_
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Union


def test():
    # type: () -> Any

    def classify(number):
        # type: (Union[float, int]) -> Union[str, Error]
        if number == 42:
            return "Answer to the Ultimate Question of Life, the Universe, and Everything."
        return Error("Insignificant.")

    assert "Answer to the Ultimate Question of Life, the Universe, and Everything." == try_(
        classify(42)
    )

    assert "Answer to the Ultimate Question of Life, the Universe, and Everything." == catch(
        try_, classify(42)
    )

    with pytest.raises(ResultError) as exc_info:
        try_(classify(1 / 137))
    assert ResultError(Error("Insignificant.")) == exc_info.value

    assert Error("Insignificant.") == catch(try_, classify(1 / 137))
