# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

import pytest

from pex.interpreter_constraints import InterpreterConstraint
from pex.pep_440 import Version
from pex.pip.version import PipVersion, PipVersionValue
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


# N.B.: awscli==1.28.1 Only resolves with the pip-2020-resolver for Pip versions earlier than 22.
# In the end this means only Pip >=20.3.2,<22 can run this test successfully. The underlying issue
# comes from PyYAML and is documented here: https://github.com/yaml/pyyaml/issues/601
@pytest.mark.parametrize(
    "pip_version",
    [
        pytest.param(pip_version, id=str(pip_version))
        for pip_version in PipVersion.values()
        # MyPy fails to typecheck <= under Python 2.7 only, even though Version has @total_ordering
        # applied.
        if Version("20.3.2") <= pip_version.version < Version("22")  # type: ignore[operator]
    ],
)
def test_backtracking(
    tmpdir,  # type: Any
    pip_version,  # type: PipVersionValue
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "-v",
        "-o",
        lock,
        "--indent",
        "2",
        "--pip-version",
        str(pip_version),
        "--resolver-version",
        "pip-2020-resolver",
        "--interpreter-constraint",
        "CPython==3.11.*",
        "--style",
        "universal",
        "--target-system",
        "linux",
        "--target-system",
        "mac",
        "--manylinux",
        "manylinux2014",
        "awscli==1.28.1",
    ).assert_success()

    try:
        python311 = next(InterpreterConstraint.parse("CPython==3.11.*").iter_matching())
    except StopIteration:
        pytest.skip("Skipping lock verification since no CPython 3.11 interpreter is available.")

    result = run_pex_command(
        args=[
            "--lock",
            lock,
            "-c",
            "aws",
            "--",
            "--version",
        ],
        python=python311.binary,
    )
    result.assert_success()
    assert result.output.startswith("aws-cli/1.28.1 "), result.output
