# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys

from _pytest.config import hookimpl

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Generator

    from _pytest.nodes import Item
    from _pytest.reports import TestReport


@hookimpl(tryfirst=True, **{"wrapper" if sys.version_info[:2] >= (3, 7) else "hookwrapper": True})
def track_status_hook(
    item,  # type: Item
    call,  # type: Any
):
    # type: (...) -> Generator[None, TestReport, TestReport]

    from testing.pytest_utils.track_status_hook import mark_passed

    report = yield
    if sys.version_info[:2] < (3, 7):
        report = report.get_result()
    if report.when == "call" and report.passed:
        mark_passed(item)
    return report
