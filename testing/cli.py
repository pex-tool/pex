# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys

from pex.typing import TYPE_CHECKING
from testing import IntegResults, installed_pex_wheel_venv_python

if TYPE_CHECKING:
    from typing import Any, Text


def run_pex3(
    *args,  # type: Text
    **kwargs  # type: Any
):
    # type: (...) -> IntegResults

    python_exe = kwargs.pop("python", None) or sys.executable
    python = (
        installed_pex_wheel_venv_python(python_exe)
        if kwargs.pop("use_pex_whl_venv", True)
        else python_exe
    )
    cmd = [python, "-mpex.cli"] + list(args)
    process = subprocess.Popen(args=cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    stdout, stderr = process.communicate()
    return IntegResults(
        cmd=tuple(cmd),
        output=stdout.decode("utf-8"),
        error=stderr.decode("utf-8"),
        return_code=process.returncode,
    )
