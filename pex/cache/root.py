# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import appdirs  # vendor:skip
else:
    from pex.third_party import appdirs


_USER_DIR = os.path.realpath(os.path.expanduser("~"))
_CACHE_DIR = os.path.realpath(
    appdirs.user_cache_dir(appauthor="pex-tool.org", appname="pex")
)  # type: str


def path(expand_user=True):
    # type: (bool) -> str

    if expand_user or _USER_DIR != commonpath((_USER_DIR, _CACHE_DIR)):
        return _CACHE_DIR
    return os.path.join("~", os.path.relpath(_CACHE_DIR, _USER_DIR))
