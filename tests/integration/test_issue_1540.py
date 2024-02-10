# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
from textwrap import dedent

from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_derive_consistent_shebang_platforms(
    tmpdir,  # type: Any
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")

    def read_pex_shebang():
        # type: () -> bytes
        with open(pex, "rb") as fp:
            return fp.readline()

    run_pex_command(args=["--platform", "linux_x86_64-cp-311-cp311", "-o", pex]).assert_success()
    assert b"#!/usr/bin/env python3.11\n" == read_pex_shebang()

    run_pex_command(
        args=[
            "--platform",
            "linux_x86_64-cp-311-cp311",
            "--platform",
            "macosx_10.9_x86_64-cp-311-cp311",
            "-o",
            pex,
        ]
    ).assert_success()
    assert b"#!/usr/bin/env python3.11\n" == read_pex_shebang()

    run_pex_command(
        args=[
            "--platform",
            "linux_x86_64-cp-3.11.5-cp311",
            "--platform",
            "macosx_10.9_x86_64-cp-311-cp311",
            "-o",
            pex,
        ]
    ).assert_success()
    assert b"#!/usr/bin/env python3.11\n" == read_pex_shebang()

    result = run_pex_command(
        args=[
            "--platform",
            "linux_x86_64-cp-310-cp310",
            "--platform",
            "macosx_10.9_x86_64-cp-311-cp311",
            "-o",
            pex,
        ]
    )
    result.assert_success()
    current_interpreter_shebang = current_interpreter.identity.hashbang()
    assert (
        "{shebang}\n".format(shebang=current_interpreter_shebang).encode("utf-8")
        == read_pex_shebang()
    )
    assert (
        dedent(
            """\
            PEXWarning: Could not calculate a targeted shebang for:
            abbreviated platform cp310-cp310-linux_x86_64
            abbreviated platform cp311-cp311-macosx_10_9_x86_64

            Using shebang: {shebang}
            If this is not appropriate, you can specify a custom shebang using the --python-shebang option.
            """
        ).format(shebang=current_interpreter_shebang)
        in result.error
    )
