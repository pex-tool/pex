# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import fcntl

from pex.fs.lock import FileLock

# N.B.: Some locks are used under thread pools; so we need to use BSD style locks to work in these
# scenarios instead of POSIX locks.
#
# BSD style locks (`flock`) are not as portable as POSIX style locks (`fcntl`) - POSIX style locks
# can work under some NFS implementations - but work with threading unlike POSIX locks which are
# subject to threading-unaware deadlock detection per the standard. Linux, in fact, implements
# deadlock detection for POSIX locks; so we can (and have) run afoul of false EDEADLCK errors under
# the right interleaving of processes and threads.


class UnixFileLock(FileLock):
    @classmethod
    def acquire(
        cls,
        fd,  # type: int
        exclusive,  # type: bool
    ):
        # type: (...) -> UnixFileLock

        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        return cls(locked_fd=fd, unlock=lambda: cls.release_lock(fd))

    @classmethod
    def release_lock(cls, fd):
        # type: (int) -> None

        fcntl.flock(fd, fcntl.LOCK_UN)
