# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

from pex.executables import is_python_script
from pex.os import WINDOWS
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import InvalidVirtualenvError, Virtualenv

if TYPE_CHECKING:
    from typing import Any, List, Optional, Sequence


PIPE = subprocess.PIPE
STDOUT = subprocess.STDOUT
CalledProcessError = subprocess.CalledProcessError


def _maybe_load_pex_info(path):
    # type: (str) -> Optional[PexInfo]
    try:
        return PexInfo.from_pex(path)
    except (KeyError, IOError, OSError):
        return None


def _safe_args(args):
    # type: (Sequence[str]) -> List[str]
    if WINDOWS:
        argv0 = args[0]
        pex_info = _maybe_load_pex_info(argv0)
        if pex_info and is_python_script(argv0, check_executable=False):
            try:
                return [Virtualenv(os.path.dirname(argv0)).interpreter.binary] + list(args)
            except InvalidVirtualenvError:
                pass
        if pex_info or argv0.endswith(".py"):
            return [sys.executable] + list(args)
    return args if isinstance(args, list) else list(args)


def call(
    args,  # type: Sequence[str]
    **kwargs  # type: Any
):
    # type: (...) -> int
    return subprocess.call(args=_safe_args(args), **kwargs)


def check_call(
    args,  # type: Sequence[str]
    **kwargs  # type: Any
):
    # type: (...) -> None
    subprocess.check_call(args=_safe_args(args), **kwargs)


def check_output(
    args,  # type: Sequence[str]
    **kwargs  # type: Any
):
    # type: (...) -> bytes
    return cast(bytes, subprocess.check_output(args=_safe_args(args), **kwargs))


class Popen(subprocess.Popen):
    def __init__(
        self,
        args,  # type: Sequence[str]
        **kwargs  # type: Any
    ):
        super(Popen, self).__init__(_safe_args(args), **kwargs)  # type: ignore[call-arg]
