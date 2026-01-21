# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys

from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import ALL_PY_VERSIONS, ensure_python_interpreter, make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import List


def test_selection_strategy(tmpdir):
    # type: (Tempdir) -> None

    candidate_pythons = []  # type: List[PythonInterpreter]
    for version in ALL_PY_VERSIONS:
        if sys.version_info[:2] != tuple(map(int, version.split(".")[:2])):
            candidate_pythons.append(
                PythonInterpreter.from_binary(ensure_python_interpreter(version))
            )
    assert len(candidate_pythons) >= 2

    sorted_pythons = sorted(candidate_pythons, key=lambda interpreter: interpreter.version)
    min_python = sorted_pythons[0]
    max_python = sorted_pythons[-1]
    assert min_python != max_python
    assert min_python.version[:2] < max_python.version[:2]

    def create_pex(
        name,  # type: str
        *extra_args  # type: str
    ):
        # type: (...) -> str
        pex = tmpdir.join(name)
        args = ["--python-shebang", "/usr/bin/env python", "-o", pex]
        for interpreter in sorted_pythons:
            args.append("--interpreter-constraint")
            args.append(
                "=={major}.{minor}.*".format(
                    major=interpreter.version[0], minor=interpreter.version[1]
                )
            )
        args.extend(extra_args)
        run_pex_command(args=args).assert_success()
        return pex

    def assert_selected(
        pex,  # type: str
        expected_python,  # type: PythonInterpreter
    ):
        # type: (...) -> None
        assert expected_python == PythonInterpreter.from_binary(
            str(
                subprocess.check_output(
                    args=[sys.executable, pex, "-c", "import sys; print(sys.executable)"],
                    env=make_env(
                        PEX_PYTHON_PATH=os.pathsep.join(
                            interpreter.binary for interpreter in sorted_pythons
                        )
                    ),
                )
                .decode("utf-8")
                .strip()
            )
        )

    assert_selected(create_pex("default"), min_python)
    assert_selected(create_pex("oldest", "--interpreter-selection-strategy", "oldest"), min_python)
    assert_selected(create_pex("newest", "--interpreter-selection-strategy", "newest"), max_python)
