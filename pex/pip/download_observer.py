# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.pip.log_analyzer import LogAnalyzer
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Mapping, Optional, Text

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Patch(object):
    code = attr.ib(default=None)  # type: Optional[Text]
    args = attr.ib(default=())  # type: Iterable[str]
    env = attr.ib(factory=dict)  # type: Mapping[str, str]


@attr.s(frozen=True)
class DownloadObserver(object):
    analyzer = attr.ib()  # type: Optional[LogAnalyzer]
    patch = attr.ib()  # type: Patch
