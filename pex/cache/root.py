# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex.compatibility import safe_commonpath
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import appdirs  # vendor:skip
else:
    from pex.third_party import appdirs


def _user_dir():
    # type: () -> str
    return os.path.realpath(os.path.expanduser("~"))


def _cache_dir():
    # type: () -> str
    return cast(str, os.path.realpath(appdirs.user_cache_dir(appauthor=False, appname="pex")))


_USER_DIR = _user_dir()
_CACHE_DIR = _cache_dir()


def path(
    expand_user=True,  # type: bool
    cache=True,  # type: bool
):
    # type: (...) -> str

    if cache:
        return _path(_USER_DIR, _CACHE_DIR, expand_user)
    return _path(_user_dir(), _cache_dir(), expand_user)


def _path(
    user_dir,  # type: str
    cache_dir,  # type: str
    expand_user=True,  # type: bool
):
    # type: (...) -> str

    if expand_user or user_dir != safe_commonpath((user_dir, cache_dir)):
        return cache_dir
    return os.path.join("~", os.path.relpath(cache_dir, user_dir))
