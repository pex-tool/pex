# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

from _pytest.config import hookimpl  # type: ignore[import]

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Generator

    from _pytest.nodes import Item  # type: ignore[import]
    from pluggy.callers import _Result  # type: ignore[import]


@hookimpl(hookwrapper=True, tryfirst=True)
def track_status_hook(
    item,  # type: Item
    call,  # type: Any
):
    # type: (...) -> Generator[None, _Result, None]

    from testing.pytest.track_status_hook import mark_passed

    report = yield
    result = report.get_result()
    if result.when == "call" and result.passed:
        mark_passed(item)
    return
