# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import ctypes
import msvcrt
from ctypes.wintypes import BOOL, DWORD, HANDLE, LPVOID, PULONG, ULONG

from pex.fs.lock import FileLock
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


class Offset(ctypes.Structure):
    _fields_ = [
        ("Offset", DWORD),
        ("OffsetHigh", DWORD),
    ]


class OffsetUnion(ctypes.Union):
    _fields_ = [("Offset", Offset), ("Pointer", LPVOID)]


# See: https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ns-minwinbase-overlapped
class Overlapped(ctypes.Structure):
    @classmethod
    def ignored(cls):
        # type: () -> Overlapped
        return cls(PULONG(ULONG(0)), PULONG(ULONG(0)), OffsetUnion(Offset(0, 0)), HANDLE(0))

    _fields_ = [
        ("Internal", PULONG),
        ("InternalHigh", PULONG),
        ("OffsetUnion", OffsetUnion),
        ("hEvent", HANDLE),
    ]


# See: https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex
_LockFileEx = ctypes.windll.kernel32.LockFileEx  # type: ignore[attr-defined]
_LockFileEx.argtypes = (
    HANDLE,  # hFile
    DWORD,  # dwFlags
    DWORD,  # dwReserved
    DWORD,  # nNumberOfBytesToLockLow
    DWORD,  # nNumberOfBytesToLockHigh
    Overlapped,  # lpOverlapped
)
_LockFileEx.restype = BOOL
_LOCKFILE_EXCLUSIVE_LOCK = 0x2


# See: https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-unlockfileex
_UnlockFileEx = ctypes.windll.kernel32.UnlockFileEx  # type: ignore[attr-defined]
_UnlockFileEx.argtypes = (
    HANDLE,  # hFile
    DWORD,  # dwReserved
    DWORD,  # nNumberOfBytesToLockLow
    DWORD,  # nNumberOfBytesToLockHigh
    Overlapped,  # lpOverlapped
)
_UnlockFileEx.restype = BOOL


class WindowsFileLock(FileLock):
    @classmethod
    def acquire(
        cls,
        fd,  # type: int
        exclusive,  # type: bool
    ):
        # type: (...) -> WindowsFileLock

        mode = 0  # The default is a shared lock.
        if exclusive:
            mode |= _LOCKFILE_EXCLUSIVE_LOCK

        overlapped = Overlapped.ignored()
        fhandle = msvcrt.get_osfhandle(fd)  # type: ignore[attr-defined]
        if not _LockFileEx(
            HANDLE(fhandle),  # hFile
            DWORD(mode),  # dwFlags
            DWORD(0),  # dwReserved
            DWORD(1),  # nNumberOfBytesToLockLow
            DWORD(0),  # nNumberOfBytesToLockHigh
            overlapped,  # lpOverlapped
        ):
            raise ctypes.WinError()  # type: ignore[attr-defined]
        return cls(locked_fd=fd, unlock=lambda: cls.release_lock(fd, overlapped=overlapped))

    @classmethod
    def release_lock(
        cls,
        fd,  # type: int
        overlapped=None,  # type: Optional[Overlapped]
    ):
        # type: (...) -> None

        fhandle = msvcrt.get_osfhandle(fd)  # type: ignore[attr-defined]
        if not _UnlockFileEx(
            HANDLE(fhandle),  # hFile
            DWORD(0),  # dwReserved
            DWORD(1),  # nNumberOfBytesToLockLow
            DWORD(0),  # nNumberOfBytesToLockHigh
            overlapped or Overlapped.ignored(),  # lpOverlapped
        ):
            raise ctypes.WinError()  # type: ignore[attr-defined]
