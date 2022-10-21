# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import fcntl
import os
import threading
from contextlib import contextmanager

from pex import pex_warnings
from pex.common import safe_mkdir, safe_rmtree
from pex.enum import Enum
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Callable, Iterator, Optional


class AtomicDirectory(object):
    def __init__(self, target_dir):
        # type: (str) -> None
        self._target_dir = target_dir
        self._work_dir = "{}.workdir".format(target_dir)

    @property
    def work_dir(self):
        # type: () -> str
        return self._work_dir

    @property
    def target_dir(self):
        # type: () -> str
        return self._target_dir

    def is_finalized(self):
        # type: () -> bool
        return os.path.exists(self._target_dir)

    def finalize(self, source=None):
        # type: (Optional[str]) -> None
        """Rename `work_dir` to `target_dir` using `os.rename()`.

        :param source: An optional source offset into the `work_dir`` to use for the atomic update
                       of `target_dir`. By default, the whole `work_dir` is used.

        If a race is lost and `target_dir` already exists, the `target_dir` dir is left unchanged and
        the `work_dir` directory will simply be removed.
        """
        if self.is_finalized():
            return

        source = os.path.join(self._work_dir, source) if source else self._work_dir
        try:
            # Perform an atomic rename.
            #
            # Per the docs: https://docs.python.org/2.7/library/os.html#os.rename
            #
            #   The operation may fail on some Unix flavors if src and dst are on different
            #   filesystems. If successful, the renaming will be an atomic operation (this is a
            #   POSIX requirement).
            #
            # We have satisfied the single filesystem constraint by arranging the `work_dir` to be a
            # sibling of the `target_dir`.
            os.rename(source, self._target_dir)
        except OSError as e:
            if e.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise e
        finally:
            self.cleanup()

    def cleanup(self):
        # type: () -> None
        safe_rmtree(self._work_dir)


class FileLockStyle(Enum["FileLockStyle.Value"]):
    class Value(Enum.Value):
        pass

    BSD = Value("bsd")
    POSIX = Value("posix")


def _is_bsd_lock(lock_style=None):
    # type: (Optional[FileLockStyle.Value]) -> bool

    # The atomic_directory file locking has used POSIX locks since inception. These have maximum
    # compatibility across OSes and stand a decent chance of working over modern NFS. With the
    # introduction of `pex3 lock ...` a limited set of atomic_directory uses started asking for BSD
    # locks since they operate in a thread pool. Only those uses actually pass an explicit value for
    # `lock_style` to atomic_directory. In order to allow experimenting with / debugging possible
    # file locking bugs, we allow a `_PEX_FILE_LOCK_STYLE` back door private ~API to upgrade all
    # locks to BSD style locks. This back door can be removed at any time.
    file_lock_style = lock_style or FileLockStyle.for_value(
        os.environ.get("_PEX_FILE_LOCK_STYLE", FileLockStyle.POSIX.value)
    )
    return file_lock_style is FileLockStyle.BSD


@contextmanager
def atomic_directory(
    target_dir,  # type: str
    lock_style=None,  # type: Optional[FileLockStyle.Value]
    source=None,  # type: Optional[str]
):
    # type: (...) -> Iterator[AtomicDirectory]
    """A context manager that yields an exclusively locked AtomicDirectory.

    :param target_dir: The target directory to atomically update.
    :param lock_style: By default, a POSIX fcntl lock will be used to ensure exclusivity.
    :param source: An optional source offset into the work directory to use for the atomic update
                   of the target directory. By default, the whole work directory is used.

    If the `target_dir` already exists the enclosed block will be yielded an AtomicDirectory that
    `is_finalized` to signal there is no work to do.

    If the enclosed block fails the `target_dir` will not be created if it does not already exist.

    The new work directory will be cleaned up regardless of whether the enclosed block succeeds.
    """

    # We use double-checked locking with the check being target_dir existence and the lock being an
    # exclusive blocking file lock.

    atomic_dir = AtomicDirectory(target_dir=target_dir)
    if atomic_dir.is_finalized():
        # Our work is already done for us so exit early.
        yield atomic_dir
        return

    head, tail = os.path.split(atomic_dir.target_dir)
    if head:
        safe_mkdir(head)
    lockfile = os.path.join(head, ".{}.atomic_directory.lck".format(tail or "here"))

    # N.B.: We don't actually write anything to the lock file but the fcntl file locking
    # operations only work on files opened for at least write.
    lock_fd = os.open(lockfile, os.O_CREAT | os.O_WRONLY)

    lock_api = cast(
        "Callable[[int, int], None]",
        fcntl.flock if _is_bsd_lock(lock_style) else fcntl.lockf,
    )

    def unlock():
        # type: () -> None
        try:
            lock_api(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    # N.B.: Since lockf and flock operate on an open file descriptor and these are
    # guaranteed to be closed by the operating system when the owning process exits,
    # this lock is immune to staleness.
    lock_api(lock_fd, fcntl.LOCK_EX)  # A blocking write lock.
    if atomic_dir.is_finalized():
        # We lost the double-checked locking race and our work was done for us by the race
        # winner so exit early.
        try:
            yield atomic_dir
        finally:
            unlock()
        return

    # If there is an error making the work_dir that means that either file-locking guarantees have
    # failed somehow and another process has the lock and has made the work_dir already or else a
    # process holding the lock ended abnormally.
    try:
        os.mkdir(atomic_dir.work_dir)
    except OSError as e:
        ident = "[pid:{pid}, tid:{tid}, cwd:{cwd}]".format(
            pid=os.getpid(), tid=threading.current_thread().ident, cwd=os.getcwd()
        )
        pex_warnings.warn(
            "{ident}: After obtaining an exclusive lock on {lockfile}, failed to establish a work "
            "directory at {workdir} due to: {err}".format(
                ident=ident,
                lockfile=lockfile,
                workdir=atomic_dir.work_dir,
                err=e,
            ),
        )
        if e.errno != errno.EEXIST:
            raise
        pex_warnings.warn(
            "{ident}: Continuing to forcibly re-create the work directory at {workdir}.".format(
                ident=ident,
                workdir=atomic_dir.work_dir,
            )
        )
        safe_mkdir(atomic_dir.work_dir, clean=True)

    try:
        yield atomic_dir
    except Exception:
        atomic_dir.cleanup()
        raise
    else:
        atomic_dir.finalize(source=source)
    finally:
        unlock()
