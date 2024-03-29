# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import subprocess
import sys

from pex.typing import TYPE_CHECKING
from testing import IntegResults

if TYPE_CHECKING:
    from typing import Any


def run_pex3(
    *args,  # type: str
    **popen_kwargs  # type: Any
):
    # type: (...) -> IntegResults
    process = subprocess.Popen(
        args=[sys.executable, "-mpex.cli"] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs
    )
    stdout, stderr = process.communicate()
    return IntegResults(
        output=stdout.decode("utf-8"), error=stderr.decode("utf-8"), return_code=process.returncode
    )
