# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import fcntl
import itertools
import os
from contextlib import contextmanager

from pex.common import safe_mkdir, touch
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple, Union

    from pex.cache.dirs import UnzipDir, VenvDir, VenvDirs  # noqa


# N.B.: The lock file path is last in the lock state tuple to allow for a simple encoding scheme in
# `save_lock_state` that is impervious to a delimiter collision in the lock file path when decoding
# in `_maybe_restore_lock_state` (due to maxsplit).

_LOCK = None  # type: Optional[Tuple[bool, int, str]]

_PEX_CACHE_ACCESS_LOCK_ENV_VAR = "_PEX_CACHE_ACCESS_LOCK"


def save_lock_state():
    # type: () -> None
    """Records any current lock state in a manner that can survive un-importing of this module."""

    # N.B.: This supports the sole case of a Pex PEX, whose runtime obtains a lock that it must hand
    # off to the Pex CLI it spawns.

    global _LOCK
    if _LOCK is not None:
        exclusive, lock_fd, lock_file = _LOCK
        os.environ[_PEX_CACHE_ACCESS_LOCK_ENV_VAR] = "|".join(
            (str(int(exclusive)), str(lock_fd), lock_file)
        )


def _maybe_restore_lock_state():
    # type: () -> None

    saved_lock_state = os.environ.pop(_PEX_CACHE_ACCESS_LOCK_ENV_VAR, None)
    if saved_lock_state:
        encoded_exclusive, encoded_lock_fd, lock_file = saved_lock_state.split("|", 2)
        global _LOCK
        _LOCK = bool(int(encoded_exclusive)), int(encoded_lock_fd), lock_file


def _lock(exclusive):
    # type: (bool) -> str

    lock_fd = None  # type: Optional[int]

    global _LOCK
    if _LOCK is None:
        _maybe_restore_lock_state()
    if _LOCK is not None:
        existing_exclusive, lock_fd, existing_lock_file = _LOCK
        if existing_exclusive == exclusive:
            return existing_lock_file

    lock_file = os.path.join(ENV.PEX_ROOT, "access.lck")

    if lock_fd is None:
        # N.B.: We don't actually write anything to the lock file but the fcntl file locking
        # operations only work on files opened for at least write.
        safe_mkdir(os.path.dirname(lock_file))
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_WRONLY)

    # N.B.: Since flock operates on an open file descriptor and these are
    # guaranteed to be closed by the operating system when the owning process exits,
    # this lock is immune to staleness.
    fcntl.flock(lock_fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

    _LOCK = exclusive, lock_fd, lock_file
    return lock_file


def read_write():
    # type: () -> str
    """Obtains the shared Pex cache read-write lock.

    This function blocks until it is safe to use the Pex cache.
    """
    return _lock(exclusive=False)


@contextmanager
def await_delete_lock():
    # type: () -> Iterator[str]
    """Awaits the Pex cache delete lock, yielding the lock file path.

    When the context manager exits, the delete lock is held, and it is safe to delete all or
    portions of the Pex cache.
    """
    lock_file = _lock(exclusive=False)
    yield lock_file
    _lock(exclusive=True)


LAST_ACCESS_FILE = ".last-access"


def _last_access_file(pex_dir):
    # type: (Union[UnzipDir, VenvDir, VenvDirs]) -> str
    return os.path.join(pex_dir.path, LAST_ACCESS_FILE)


def record_access(
    pex_dir,  # type: Union[UnzipDir, VenvDir]
    last_access=None,  # type: Optional[float]
):
    # type: (...) -> None

    touch(_last_access_file(pex_dir), last_access)


def iter_all_cached_pex_dirs():
    # type: () -> Iterator[Tuple[Union[UnzipDir, VenvDirs], float]]

    from pex.cache.dirs import UnzipDir, VenvDirs

    pex_dirs = itertools.chain(
        UnzipDir.iter_all(), VenvDirs.iter_all()
    )  # type: Iterator[Union[UnzipDir, VenvDirs]]
    for pex_dir in pex_dirs:
        last_access = os.stat(_last_access_file(pex_dir)).st_mtime
        yield pex_dir, last_access
