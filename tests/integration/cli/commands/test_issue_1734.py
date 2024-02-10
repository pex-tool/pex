# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess

from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import InterpreterConstraint
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


def test_lock_create_sdist_requires_python_different_from_current(
    tmpdir,  # type: Any
    py27,  # type: PythonInterpreter
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock")
    create_lock_args = [
        "lock",
        "create",
        "--resolver-version",
        "pip-2020-resolver",
        "--style",
        "universal",
        "--interpreter-constraint",
        "CPython<3.11,>=3.8",
        "--python-path",
        os.pathsep.join(interp.binary for interp in (py27, py38, py310)),
        "aioconsole==0.4.1",
        "-o",
        lock,
        "--indent",
        "2",
    ]

    # 1st prove this does the wrong thing on prior broken versions of Pex.
    result = run_pex_command(
        args=["pex==2.1.82", "-c", "pex3", "--"] + create_lock_args,
        python=py27.binary,
        quiet=True,
    )
    result.assert_failure()
    assert (
        "ERROR: Package 'aioconsole' requires a different Python: {pyver} not in '>=3.7'".format(
            pyver=py27.identity.version_str
        )
        in result.error.splitlines()
    )

    # Now show it currently works.
    subprocess.check_call(
        args=[py27.binary, "-m", "pex.cli"] + create_lock_args + ["--pip-version", "20.3.4-patched"]
    )
    run_pex_command(
        args=["--lock", lock, "--", "-c", "import aioconsole"],
        python=py310.binary,
    ).assert_success()


def test_lock_create_universal_interpreter_constraint_unsatisfiable(
    tmpdir,  # type: Any
    py27,  # type: PythonInterpreter
    py38,  # type: PythonInterpreter
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock")
    result = run_pex3(
        "lock",
        "create",
        "--resolver-version",
        "pip-2020-resolver",
        "--style",
        "universal",
        "--interpreter-constraint",
        "CPython<3.11,>=3.9",
        "--python-path",
        os.pathsep.join(interp.binary for interp in (py27, py38)),
        "aioconsole==0.4.1",
        "-o",
        lock,
        "--indent",
        "2",
    )
    result.assert_failure()
    assert re.match(
        r"^When creating a universal lock with an --interpreter-constraint, an interpreter "
        r"matching the constraint must be found on the local system but none was: Could not find a "
        r"compatible interpreter\.\n"
        r"\n"
        r"Examined the following interpreters:\n"
        r"1\.\)\s+{py27_path} {py27_req}\n"
        r"2\.\)\s+{py38_path} {py38_req}\n"
        r"\n"
        r"No interpreter compatible with the requested constraints was found:\n"
        r"\n"
        r"  Version matches CPython<3\.11,>=3\.9\n".format(
            py27_path=py27.binary,
            py27_req=InterpreterConstraint.exact_version(py27),
            py38_path=py38.binary,
            py38_req=InterpreterConstraint.exact_version(py38),
        ),
        result.error,
    )
