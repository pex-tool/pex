# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

from pex.os import WINDOWS
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, List


def subprocess_daemon_kwargs():
    # type: () -> Dict[str, Any]

    if WINDOWS:
        return {
            "creationflags": (
                # The subprocess.{DETACHED_PROCESS,CREATE_NEW_PROCESS_GROUP} attributes are only
                # defined on Windows.
                subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
                | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            )
        }
    elif sys.version_info[:2] >= (3, 2):
        return {"start_new_session": True}
    else:
        return {
            # The os.setsid function is not available on Windows.
            "preexec_fn": os.setsid  # type: ignore[attr-defined]
        }


def launch_python_daemon(
    args,  # type: List[str]
    **kwargs  # type: Any
):
    # type: (...) -> subprocess.Popen
    if WINDOWS:
        python, _ = os.path.splitext(os.path.basename(args[0]))
        if python == "python":
            pythonw = os.path.join(os.path.dirname(args[0]), "pythonw.exe")
            if os.path.exists(pythonw):
                args[0] = pythonw
    kwargs.update(subprocess_daemon_kwargs())
    return subprocess.Popen(args=args, **kwargs)
