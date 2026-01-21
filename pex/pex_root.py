# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import atexit
import os
import shutil
import tempfile
from contextlib import contextmanager

from pex import pex_warnings
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterator, Optional, Tuple

_FALLBACK = None  # type: Optional[str]


def _cleanup_fallback():
    # type: () -> None

    global _FALLBACK
    if _FALLBACK and os.path.exists(_FALLBACK):
        shutil.rmtree(_FALLBACK, True)


def can_write_dir(path):
    # type: (str) -> bool
    while not os.access(path, os.F_OK):
        parent_path = os.path.dirname(path)
        if not parent_path or (parent_path == path):
            # We've recursed up to the root without success, which shouldn't happen,
            return False
        path = parent_path
    return os.path.isdir(path) and os.access(path, os.R_OK | os.W_OK | os.X_OK)


def ensure_writeable(raw_pex_root):
    # type: (str) -> Tuple[str, bool]

    pex_root = os.path.realpath(os.path.expanduser(raw_pex_root))
    is_fallback = False
    if not can_write_dir(pex_root):
        fallback = os.environ.pop("_PEX_ROOT_FALLBACK", None)
        if not fallback:
            fallback = os.path.realpath(
                tempfile.mkdtemp(prefix="pex-root.", suffix=".readonly-fallback")
            )
        pex_warnings.warn(
            "PEX_ROOT is configured as {pex_root} but that path is un-writeable, "
            "falling back to a temporary PEX_ROOT of {fallback} which will hurt "
            "performance.".format(pex_root=pex_root, fallback=fallback)
        )
        global _FALLBACK
        pex_root = _FALLBACK = fallback
        is_fallback = True
        atexit.register(_cleanup_fallback)
    return pex_root, is_fallback


@contextmanager
def preserve_fallback():
    # type: () -> Iterator[Dict[str, str]]

    global _FALLBACK
    fallback = _FALLBACK
    _FALLBACK = None

    env = os.environ.copy()
    if fallback:
        env["_PEX_ROOT_FALLBACK"] = fallback
    try:
        yield env
    finally:
        if fallback:
            _FALLBACK = fallback
