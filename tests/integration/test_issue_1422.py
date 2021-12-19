# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess
import sys

from pex.testing import PY27, PY37, PY310, ensure_python_interpreter, make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterable, Optional, Tuple


def test_unconstrained_universal_venv_pex(tmpdir):
    # type: (Any) -> None
    setuptools_pex = os.path.join(str(tmpdir), "setuptools.pex")
    run_pex_command(args=["setuptools==44.0.0", "-o", setuptools_pex, "--venv"]).assert_success()

    def execute_pex(
        python,  # type: str
        **extra_env  # type: str
    ):
        # type: (...) -> Tuple[bytes, bytes, int]
        process = subprocess.Popen(
            args=[
                python,
                setuptools_pex,
                "-c",
                "import sys; print('.'.join(map(str, sys.version_info[:2])))",
            ],
            env=make_env(PEX_VERBOSE=1, **extra_env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        return stdout, stderr, process.returncode

    def assert_uses_python(
        python,  # type: str
        expected_version,  # type: Tuple[int, int]
        expected_warnings=None,  # type: Optional[Iterable[str]]
        **extra_env  # type: str
    ):
        # type: (...) -> None
        stdout, stderr, returncode = execute_pex(python, **extra_env)
        assert 0 == returncode, stderr
        assert ".".join(map(str, expected_version)) == stdout.decode("utf-8").strip()

        stderr_text = stderr.decode("utf-8").strip()
        if expected_warnings:
            assert "PEXWarning" in stderr_text
            for expected_warning in expected_warnings:
                assert re.search(expected_warning, stderr_text)
        else:
            assert "PEXWarning" not in stderr_text

    py27 = ensure_python_interpreter(PY27)
    py37 = ensure_python_interpreter(PY37)
    py310 = ensure_python_interpreter(PY310)

    assert_uses_python(python=sys.executable, expected_version=sys.version_info[:2])
    assert_uses_python(python=py27, expected_version=(2, 7))
    assert_uses_python(python=py37, expected_version=(3, 7))
    assert_uses_python(python=py310, expected_version=(3, 10))

    # When PEX_PYTHON is imprecise, the final python should be chosen by the PEX runtime.
    py27_ppp = os.path.dirname(py27)
    assert_uses_python(
        python=py310,
        expected_version=(2, 7),
        PEX_PYTHON="python3.7",
        PEX_PYTHON_PATH=py27_ppp,
        expected_warnings=[
            r"Using a venv restricted by PEX_PYTHON_PATH={ppp} for {pex} at ".format(
                ppp=py27_ppp, pex=setuptools_pex
            )
        ],
    )

    # When PEX_PYTHON is imprecise and not locked down to a minor version, a warning should be
    # issued.
    assert_uses_python(
        python=py310,
        expected_version=(2, 7),
        PEX_PYTHON="python3",
        PEX_PYTHON_PATH=py27_ppp,
        expected_warnings=[
            r"Using a venv selected by PEX_PYTHON=python3 for {pex} at".format(pex=setuptools_pex),
            r"Using a venv restricted by PEX_PYTHON_PATH={ppp} for {pex} at ".format(
                ppp=py27_ppp, pex=setuptools_pex
            ),
        ],
    )

    # When PEX_PYTHON is precise but not on PEX_PYTHON_PATH, the final python should also be chosen
    # by the PEX runtime and selection should fail.
    _, _, returncode = execute_pex(python=py310, PEX_PYTHON=py37, PEX_PYTHON_PATH=py27_ppp)
    assert 0 != returncode

    # But when PEX_PYTHON is precise and on the PEX_PYTHON_PATH, the final python should be
    # PEX_PYTHON.
    assert_uses_python(
        python=py310,
        expected_version=(3, 7),
        PEX_PYTHON=py37,
        PEX_PYTHON_PATH=":".join(os.path.dirname(py) for py in (py27, py37)),
    )
