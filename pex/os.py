# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List, NoReturn, Text, Tuple, Union


class _CurrentOs(object):
    def __get__(self, obj, objtype=None):
        # type: (...) -> Os.Value
        if not hasattr(self, "_current"):
            # N.B.: Python 2.7 uses "linux2".
            if sys.platform.startswith("linux"):
                self._current = Os.LINUX
            elif sys.platform == "darwin":
                self._current = Os.MACOS
            elif sys.platform == "win32":
                self._current = Os.WINDOWS
            if not hasattr(self, "_current"):
                raise ValueError(
                    "The current operating system is not supported!: {system}".format(
                        system=sys.platform
                    )
                )
        return self._current


class Os(Enum["Os.Value"]):
    class Value(Enum.Value):
        pass

    LINUX = Value("linux")
    MACOS = Value("macos")
    WINDOWS = Value("windows")
    CURRENT = _CurrentOs()


Os.seal()

# N.B.: Python 2.7 uses "linux2".
LINUX = Os.CURRENT is Os.LINUX
MAC = Os.CURRENT is Os.MACOS
WINDOWS = Os.CURRENT is Os.WINDOWS


HOME_ENV_VAR = "USERPROFILE" if WINDOWS else "HOME"


if WINDOWS:

    def safe_execv(argv):
        # type: (Union[List[str], Tuple[str, ...]]) -> NoReturn
        import subprocess
        import sys

        sys.exit(subprocess.call(args=argv))

else:

    def safe_execv(argv):
        # type: (Union[List[str], Tuple[str, ...]]) -> NoReturn
        os.execv(argv[0], argv)


if WINDOWS:
    _GBT = None  # type: Any

    def is_exe(path):
        # type: (Text) -> bool

        if not os.path.isfile(path):
            return False

        from pex.sysconfig import EXE_EXTENSIONS

        _, ext = os.path.splitext(path)
        if ext.lower() in EXE_EXTENSIONS:
            return True

        import ctypes
        from ctypes.wintypes import BOOL, DWORD, LPCWSTR, LPDWORD

        global _GBT
        if _GBT is None:
            # https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getbinarytypew
            gbt = ctypes.windll.kernel32.GetBinaryTypeW  # type: ignore[attr-defined]
            gbt.argtypes = (
                # lpApplicationName
                LPCWSTR,
                # lpBinaryType
                LPDWORD,
            )
            gbt.restype = BOOL
            _GBT = gbt

        # N.B.: We don't care about the binary type, just the bool which tells us it is or is not an
        # executable.
        _binary_type = DWORD(0)
        return bool(_GBT(path, ctypes.byref(_binary_type)))

else:

    def is_exe(path):
        # type: (Text) -> bool
        """Determines if the given path is a file executable by the current user.

        :param path: The path to check.
        :return: `True if the given path is a file executable by the current user.
        """
        return os.path.isfile(path) and os.access(path, os.R_OK | os.X_OK)


if WINDOWS:

    # https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights
    _PROCESS_TERMINATE = 0x1  # Required to terminate a process using TerminateProcess.

    _OP = None  # type: Any
    _TP = None  # type: Any

    def kill(pid):
        # type: (int) -> None

        import ctypes
        from ctypes.wintypes import BOOL, DWORD, HANDLE, UINT

        global _OP
        if _OP is None:
            # https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess
            op = ctypes.windll.kernel32.OpenProcess  # type: ignore[attr-defined]
            op.argtypes = (
                DWORD,  # dwDesiredAccess
                BOOL,  # bInheritHandle
                DWORD,  # dwProcessId
            )
            op.restype = HANDLE
            _OP = op

        phandle = _OP(_PROCESS_TERMINATE, False, pid)
        if not phandle:
            # TODO(John Sirois): Review literature / experiment and don't raise if this just means
            #  the process is already dead.
            #  See: https://github.com/pex-tool/pex/issues/2670
            raise ctypes.WinError()  # type: ignore[attr-defined]

        global _TP
        if _TP is None:
            # https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess
            tp = ctypes.windll.kernel32.OpenProcess  # type: ignore[attr-defined]
            tp.argtypes = (
                HANDLE,  # hProcess
                UINT,  # uExitCode
            )
            tp.restype = BOOL
            _TP = tp

        if not _TP(phandle, 1):
            # TODO(John Sirois): Review literature / experiment and don't raise if this just means
            #  the process is already dead (may need to consult GetLastError).
            #  See: https://github.com/pex-tool/pex/issues/2670
            raise ctypes.WinError()  # type: ignore[attr-defined]

else:

    def kill(pid):
        # type: (int) -> None

        import errno
        import signal

        try:
            os.kill(pid, signal.SIGKILL)  # type: ignore[attr-defined]
        except OSError as e:
            if e.errno != errno.ESRCH:  # No such process.
                raise
