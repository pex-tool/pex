# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys

from pex.typing import TYPE_CHECKING
from testing import IntegResults, UvPython, ensure_uv_python, installed_pex_wheel_venv_python

if TYPE_CHECKING:
    from typing import Any, Text


def run_pex3(
    *args,  # type: Text
    **kwargs  # type: Any
):
    # type: (...) -> IntegResults

    python_exe = kwargs.pop("python", None)
    if isinstance(python_exe, UvPython):
        python = ensure_uv_python(python_exe)
    elif python_exe:
        python = python_exe
    else:
        python = sys.executable

    python = (
        installed_pex_wheel_venv_python(python) if kwargs.pop("use_pex_whl_venv", True) else python
    )
    cmd = [python, "-mpex.cli"] + list(map(str, args))
    process = subprocess.Popen(args=cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    stdout, stderr = process.communicate()
    return IntegResults(
        cmd=tuple(cmd),
        output=stdout.decode("utf-8"),
        error=stderr.decode("utf-8"),
        return_code=process.returncode,
    )
