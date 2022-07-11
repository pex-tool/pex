# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess

import pytest

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.testing import PY27, ensure_python_interpreter, run_pex_command
from pex.third_party.packaging import tags
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


PY27_BINARY = ensure_python_interpreter(PY27)


def supports_platform(
    python,  # type: str
    platform_tag,  # type: str
):
    # type: (...) -> bool

    # JPype1 version 0.7.0 has CPython 2.7 published wheels with tags:
    # + cp27-cp27m-manylinux2010_x86_64
    # + cp27-cp27mu-manylinux2010_x86_64
    python_identity = PythonInterpreter.from_binary(python).identity
    tag = "{python}-{abi}-{platform}".format(
        python=python_identity.python_tag, abi=python_identity.abi_tag, platform=platform_tag
    )
    return len(python_identity.supported_tags.compatible_tags(tags.parse_tag(tag))) > 0


@pytest.mark.skipif(
    not supports_platform(PY27_BINARY, "manylinux2010_x86_64"),
    reason="Test requires a manylinux2010 x86_64 compatible platform",
)
def test_prefer_binary(tmpdir):
    # type: (Any) -> None

    result = run_pex_command(args=["JPype1"], python=PY27_BINARY)
    result.assert_failure()
    assert "ImportError: No module named pathlib" in result.error, (
        "The latest versions of JPype1 do not support Python 2.7 and their setup.py use Python 3 "
        "only features; so we expect an unconstrained resolve to pick the latest JPype1 sdist,"
        "attempt to build a wheel from it and fail."
    )

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["--prefer-binary", "JPype1", "-o", pex], python=PY27_BINARY
    ).assert_success()

    subprocess.check_call(args=[PY27_BINARY, pex, "-c", "import jpype"])
    distributions = tuple(
        PEX(pex, interpreter=PythonInterpreter.from_binary(PY27_BINARY)).resolve()
    )
    assert 1 == len(distributions)
    assert "JPype1" == distributions[0].project_name
    assert (
        "0.7.0" == distributions[0].version
    ), "The last version of JPype1 to publish a Python 2.7 compatible distribution was 0.7.0"
