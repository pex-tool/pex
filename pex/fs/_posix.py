# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import fcntl

from pex.fs.lock import FileLock, FileLockStyle
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Callable


class PosixFileLock(FileLock):
    @staticmethod
    def _lock_api(style):
        # type: (FileLockStyle.Value) -> Callable[[int, int], None]

        return cast(
            "Callable[[int, int], None]",
            fcntl.flock if style is FileLockStyle.BSD else fcntl.lockf,  # type: ignore[attr-defined]
        )

    @classmethod
    def acquire(
        cls,
        fd,  # type: int
        exclusive,  # type: bool
        style,  # type: FileLockStyle.Value
    ):
        # type: (...) -> PosixFileLock

        cls._lock_api(style)(
            fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH  # type: ignore[attr-defined]
        )
        return cls(locked_fd=fd, unlock=lambda: cls.release_lock(fd, style=style))

    @classmethod
    def release_lock(
        cls,
        fd,  # type: int
        style,  # type: FileLockStyle.Value
    ):
        # type: (...) -> None

        cls._lock_api(style)(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
