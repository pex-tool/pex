# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys

from pex.compatibility import to_unicode
from pex.typing import TYPE_CHECKING, cast
from testing import IntegResults

if TYPE_CHECKING:
    from typing import Text  # noqa
    from typing import Any


def run_pex3(
    *args,  # type: str
    **kwargs  # type: Any
):
    # type: (...) -> IntegResults

    python = cast("Text", kwargs.pop("python", to_unicode(sys.executable)))
    process = subprocess.Popen(
        args=[python, "-mpex.cli"] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs
    )
    stdout, stderr = process.communicate()
    return IntegResults(
        output=stdout.decode("utf-8"), error=stderr.decode("utf-8"), return_code=process.returncode
    )
