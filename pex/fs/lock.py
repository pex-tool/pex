# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.common import safe_mkdir
from pex.enum import Enum
from pex.os import WINDOWS
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class FileLockStyle(Enum["FileLockStyle.Value"]):
    class Value(Enum.Value):
        pass

    BSD = Value("bsd")
    POSIX = Value("posix")


FileLockStyle.seal()


@attr.s(frozen=True)
class FileLock(object):
    _locked_fd = attr.ib()  # type: int
    _unlock = attr.ib()  # type: Callable[[], Any]

    @property
    def fd(self):
        # type: () -> int
        return self._locked_fd

    def release(self):
        # type: () -> None
        try:
            self._unlock()
        finally:
            os.close(self._locked_fd)


def acquire(
    path,  # type: str
    exclusive=True,  # type: bool
    style=FileLockStyle.POSIX,  # type: FileLockStyle.Value
    fd=None,  # type: Optional[int]
):
    # type: (...) -> FileLock

    if fd:
        lock_fd = fd
    else:
        # N.B.: We don't actually write anything to the lock file but the fcntl file locking
        # operations only work on files opened for at least write.
        safe_mkdir(os.path.dirname(path))
        lock_fd = os.open(path, os.O_CREAT | os.O_WRONLY)

    if WINDOWS:
        from pex.fs._windows import WindowsFileLock

        return WindowsFileLock.acquire(lock_fd, exclusive=exclusive)
    else:
        from pex.fs._posix import PosixFileLock

        return PosixFileLock.acquire(lock_fd, exclusive=exclusive, style=style)


def release(
    fd,  # type: int
    style=FileLockStyle.POSIX,  # type: FileLockStyle.Value
):
    # type: (...) -> None

    if WINDOWS:
        from pex.fs._windows import WindowsFileLock

        WindowsFileLock.release_lock(fd)
    else:
        from pex.fs._posix import PosixFileLock

        PosixFileLock.release_lock(fd, style=style)
