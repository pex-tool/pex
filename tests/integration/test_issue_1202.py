# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess

import pytest

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.third_party.packaging import tags
from pex.typing import TYPE_CHECKING
from testing import PY27, ensure_python_interpreter, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture
def supported_py27():
    # type: (...) -> str

    python = ensure_python_interpreter(PY27)

    # JPype1 version 0.7.0 has CPython 2.7 published wheels with tags:
    # + cp27-cp27m-manylinux2010_x86_64
    # + cp27-cp27mu-manylinux2010_x86_64
    python_identity = PythonInterpreter.from_binary(python).identity
    tag = "{python}-{abi}-manylinux2010_x86_64".format(
        python=python_identity.python_tag,
        abi=python_identity.abi_tag,
    )
    if len(python_identity.supported_tags.compatible_tags(tags.parse_tag(tag))) == 0:
        pytest.skip("Test requires a manylinux2010 x86_64 compatible platform")
    return python


def test_prefer_binary(
    tmpdir,  # type: Any
    supported_py27,  # type: str
):
    # type: (...) -> None

    result = run_pex_command(args=["JPype1"], python=supported_py27)
    result.assert_failure()
    assert "ImportError: No module named pathlib" in result.error, (
        "The latest versions of JPype1 do not support Python 2.7 and their setup.py use Python 3 "
        "only features; so we expect an unconstrained resolve to pick the latest JPype1 sdist,"
        "attempt to build a wheel from it and fail."
    )

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["--prefer-binary", "JPype1", "-o", pex], python=supported_py27
    ).assert_success()

    subprocess.check_call(args=[supported_py27, pex, "-c", "import jpype"])
    distributions = tuple(
        PEX(pex, interpreter=PythonInterpreter.from_binary(supported_py27)).resolve()
    )
    assert 1 == len(distributions)
    assert "JPype1" == distributions[0].project_name
    assert (
        "0.7.0" == distributions[0].version
    ), "The last version of JPype1 to publish a Python 2.7 compatible distribution was 0.7.0"
