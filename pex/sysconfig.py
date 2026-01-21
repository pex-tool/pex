# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import os.path
import platform
import subprocess
import sys
from sysconfig import get_config_var

from pex import pex_warnings
from pex.enum import Enum
from pex.os import Os
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, Text, TypeVar

EXE_EXTENSION = get_config_var("EXE") or ""
EXE_EXTENSIONS = (
    tuple(ext.lower() for ext in os.environ.get("PATHEXT", EXE_EXTENSION).split(os.pathsep))
    if EXE_EXTENSION
    else ()
)


if TYPE_CHECKING:
    _Text = TypeVar("_Text", str, Text)


def script_name(name):
    # type: (_Text) -> _Text
    if not EXE_EXTENSION:
        return name
    stem, ext = os.path.splitext(name)
    return name if (ext and ext.lower() in EXE_EXTENSIONS) else name + EXE_EXTENSION


class _CurrentLibC(object):
    def __get__(self, obj, objtype=None):
        # type: (...) -> Optional[LibC.Value]
        if not hasattr(self, "_current"):
            self._current = None
            if Os.CURRENT is Os.LINUX:
                self._current = LibC.GLIBC
                try:
                    process = subprocess.Popen(
                        args=["ldd", sys.executable],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                except OSError as e:
                    pex_warnings.warn(
                        "Failed to detect if this interpreter is running under musl libc: "
                        "{err}".format(err=e)
                    )
                else:
                    output, _ = process.communicate()
                    if process.returncode == 0 and b"musl" in output:
                        self._current = LibC.MUSL
        return self._current


class LibC(Enum["LibC.Value"]):
    class Value(Enum.Value):
        pass

    GLIBC = Value("gnu")
    MUSL = Value("musl")
    CURRENT = _CurrentLibC()

    @classmethod
    def parse(cls, value):
        # type: (str) -> Optional[LibC.Value]
        if "current" == value:
            return cls.CURRENT
        if Os.CURRENT is Os.LINUX:
            return cls.for_value(value)
        return None


LibC.seal()


class _CurrentPlatform(object):
    def __get__(self, obj, objtype=None):
        # type: (...) -> SysPlatform.Value
        if not hasattr(self, "_current"):
            machine = platform.machine().lower()
            if Os.CURRENT is Os.LINUX:
                if machine in ("aarch64", "arm64"):
                    self._current = (
                        SysPlatform.MUSL_LINUX_AARCH64
                        if LibC.CURRENT is LibC.MUSL
                        else SysPlatform.LINUX_AARCH64
                    )
                elif machine in ("armv7l", "armv8l"):
                    self._current = SysPlatform.LINUX_ARMV7L
                elif machine == "ppc64le":
                    self._current = SysPlatform.LINUX_PPC64LE
                elif machine == "riscv64":
                    self._current = SysPlatform.LINUX_RISCV64
                elif machine == "s390x":
                    self._current = SysPlatform.LINUX_S390X
                elif machine in ("amd64", "x86_64"):
                    self._current = (
                        SysPlatform.MUSL_LINUX_X86_64
                        if LibC.CURRENT is LibC.MUSL
                        else SysPlatform.LINUX_X86_64
                    )
            if Os.CURRENT is Os.MACOS:
                if machine in ("aarch64", "arm64"):
                    self._current = SysPlatform.MACOS_AARCH64
                elif machine in ("amd64", "x86_64"):
                    self._current = SysPlatform.MACOS_X86_64
            if Os.CURRENT is Os.WINDOWS:
                if machine in ("aarch64", "arm64"):
                    self._current = SysPlatform.WINDOWS_AARCH64
                elif machine in ("amd64", "x86_64"):
                    self._current = SysPlatform.WINDOWS_X86_64
            if not hasattr(self, "_current"):
                raise ValueError(
                    "The current operating system / machine pair is not supported!: "
                    "{system} / {machine}".format(system=Os.CURRENT, machine=machine)
                )
        return self._current


class _PlatformValue(Enum.Value):
    def __init__(
        self,
        os_type,  # type: Os.Value
        arch,  # type: str
        libc=None,  # type: Optional[LibC.Value]
    ):
        self.os = os_type
        self.arch = arch
        self.libc = libc
        self.os_arch = "{os}-{arch}".format(os=os_type, arch=arch)
        super(_PlatformValue, self).__init__(
            "musl-{value}".format(value=self.os_arch) if libc is LibC.MUSL else self.os_arch
        )

    @property
    def exe_extension(self):
        # type: () -> str
        return ".exe" if self.os is Os.WINDOWS else ""

    @property
    def venv_bin_dir(self):
        # type: () -> str
        return "Scripts" if self.os is Os.WINDOWS else "bin"

    def binary_name(self, binary_name):
        # type: (_Text) -> _Text
        return "{binary_name}{extension}".format(
            binary_name=binary_name, extension=self.exe_extension
        )

    def qualified_binary_name(self, binary_name):
        # type: (_Text) -> _Text
        return "{binary_name}-{platform}{extension}".format(
            binary_name=binary_name, platform=self, extension=self.exe_extension
        )

    def qualified_file_name(self, file_name):
        # type: (_Text) -> _Text
        stem, ext = os.path.splitext(file_name)
        return "{stem}-{platform}{ext}".format(stem=stem, platform=self, ext=ext)


class SysPlatform(Enum["SysPlatform.Value"]):
    class Value(_PlatformValue):
        pass

    LINUX_AARCH64 = Value(Os.LINUX, "aarch64", LibC.GLIBC)
    MUSL_LINUX_AARCH64 = Value(Os.LINUX, "aarch64", LibC.MUSL)
    LINUX_ARMV7L = Value(Os.LINUX, "armv7l")
    LINUX_PPC64LE = Value(Os.LINUX, "powerpc64")
    LINUX_RISCV64 = Value(Os.LINUX, "riscv64")
    LINUX_S390X = Value(Os.LINUX, "s390x")
    LINUX_X86_64 = Value(Os.LINUX, "x86_64", LibC.GLIBC)
    MUSL_LINUX_X86_64 = Value(Os.LINUX, "x86_64", LibC.MUSL)
    MACOS_AARCH64 = Value(Os.MACOS, "aarch64")
    MACOS_X86_64 = Value(Os.MACOS, "x86_64")
    WINDOWS_AARCH64 = Value(Os.WINDOWS, "aarch64")
    WINDOWS_X86_64 = Value(Os.WINDOWS, "x86_64")
    CURRENT = _CurrentPlatform()

    @classmethod
    def parse(cls, value):
        # type: (str) -> SysPlatform.Value
        return cls.CURRENT if "current" == value else cls.for_value(value)


SysPlatform.seal()


# TODO(John Sirois): Consider using `sysconfig.get_path("scripts", expand=False)` in combination
#  with either sysconfig.get_config_vars() or Formatter().parse() to pick apart the script dir
#  suffix from any base dir template.
SCRIPT_DIR = SysPlatform.CURRENT.venv_bin_dir
