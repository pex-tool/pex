# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys

import pytest

from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider

if TYPE_CHECKING:
    from typing import List


@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
    ],
)
@skip_if_no_provider
def test_scie_ephemeral_run(
    tmpdir,  # type: Tempdir
    pex_wheel,  # type: str
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex_scie = tmpdir.join("pex")
    run_pex_command(
        args=[pex_wheel, "-c", "pex", "-o", pex_scie, "--scie", "eager"] + execution_mode_args
    ).assert_success()

    ic = "{impl}=={major}.{minor}.*".format(
        impl="PyPy" if IS_PYPY else "CPython", major=sys.version_info[0], minor=sys.version_info[1]
    )

    # Verify the scie can perform an ephemeral run with `-- -c`.
    output = subprocess.check_output(
        args=[
            pex_scie,
            "--interpreter-constraint",
            ic,
            "--",
            "-c",
            "import sys; print(sys.executable)",
        ],
        env=make_env(PATH=None),
    )
    assert output.decode("utf-8").strip()

    # Verify the scie can drop into a REPL via ephemeral run.
    process = subprocess.Popen(
        args=[pex_scie, "--interpreter-constraint", ic, "--"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=make_env(PATH=None),
    )
    stdout, stderr = process.communicate(input=b"import sys; print(sys.executable)\nquit()\n")
    assert process.returncode == 0, stderr.decode("utf-8")
    assert b">>>" in stdout or b">>>" in stderr
