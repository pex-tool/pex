# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable

    import appdirs  # vendor:skip
else:
    from pex.third_party import appdirs


_USER_DIR = os.path.expanduser("~")
_CACHE_DIR = appdirs.user_cache_dir(appauthor="pex-tool.org", appname="pex")  # type: str


def cache_path(
    sub_path=(),  # type: Iterable[str]
    expand_user=True,  # type: bool
):
    # type: (...) -> str

    path = os.path.join(_CACHE_DIR, *sub_path)
    if expand_user or _USER_DIR != commonpath((_USER_DIR, path)):
        return path
    return os.path.join("~", os.path.relpath(path, _USER_DIR))
