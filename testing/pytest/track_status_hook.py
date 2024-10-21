# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys

from pex.compatibility import PY2
from pex.typing import TYPE_CHECKING
from testing.pytest.tmp import RetentionPolicy

if TYPE_CHECKING:
    from typing import Dict

    from _pytest.config.argparsing import Parser  # type: ignore[import]
    from _pytest.fixtures import FixtureRequest  # type: ignore[import]
    from _pytest.nodes import Item  # type: ignore[import]
    from _pytest.reports import TestReport  # type: ignore[import]


_PASSED_STATUS = {}  # type: Dict[str, bool]


def mark_passed(node):
    # type: (Item) -> None
    _PASSED_STATUS[node.nodeid] = True


def passed(node):
    # type: (Item) -> bool
    return _PASSED_STATUS.pop(node.nodeid, False)


if PY2:
    from testing.pytest.track_status_hook_py2 import track_status_hook as _track_status_hook
else:
    from testing.pytest.track_status_hook_py3 import track_status_hook as _track_status_hook

hook = _track_status_hook


if sys.version_info[:2] < (3, 7):

    def pytest_addoption(parser):
        # type: (Parser) -> None
        parser.addini(
            "tmp_path_retention_count",
            help=(
                "How many sessions should we keep the `tmpdir` directories, according to"
                "`tmp_path_retention_policy`."
            ),
            default=3,
        )

        parser.addini(
            "tmp_path_retention_policy",
            help=(
                "Controls which directories created by the `tmpdir` fixture are kept around, based "
                "on test outcome. ({values})".format(
                    values="/".join(map(str, RetentionPolicy.values()))
                )
            ),
            default="all",
        )

else:

    def pytest_addoption(parser):
        # type: (Parser) -> None
        # The `tmp_path_retention_count` and `tmp_path_retention_policy` options are already setup
        # under the newer pytests used by our Python>=3.7 test environments.
        pass
