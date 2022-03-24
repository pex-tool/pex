# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from pex.cli.testing import run_pex3
from pex.interpreter import PythonInterpreter
from pex.pex_info import PexInfo
from pex.resolve import lockfile
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_multiplatform_sdist(
    tmpdir,  # type: Any
    py27,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    all_interpreters = (py27, py37, py310)
    python_path = ":".join((interp.binary for interp in all_interpreters))
    interpreter_selection_args = [
        "--python-path",
        python_path,
        "--interpreter-constraint",
        ">=2.7,<3.11",
    ]

    lock = os.path.join(str(tmpdir), "lock")
    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--no-wheel",
        "psutil==5.9.0",
        "-o",
        lock,
        *interpreter_selection_args
    ).assert_success()
    lock_file = lockfile.load(lock)
    assert 1 == len(lock_file.locked_resolves), "Expected 1 resolve for universal style."
    locked_resolve = lock_file.locked_resolves[0]
    assert 1 == len(
        locked_resolve.locked_requirements
    ), "Expected 1 locked requirement since psutil has no dependencies"
    locked_requirement = locked_resolve.locked_requirements[0]
    assert 0 == len(
        locked_requirement.additional_artifacts
    ), "Expected just a single sdist artifact since we specified --no-wheel."
    assert locked_requirement.artifact.url.endswith(".tar.gz"), "Expected a locked sdist URL."

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["--lock", lock, "-o", pex] + interpreter_selection_args).assert_success()

    assert 3 == len(
        PexInfo.from_pex(pex).distributions
    ), "Expected a unique platform-specific wheel to be built for each interpreter"
    for interp in all_interpreters:
        subprocess.check_call(args=[interp.binary, pex, "-c", "import psutil"])
