# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 7),
    reason="The jaraco-collections 3.5.1 distribution requires Python >=3.7",
)
def test_check_install_issue_1726(
    tmpdir,  # type: Any
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup

                setup(
                    name="pex-test",
                    version='0.1',
                    install_requires=[
                        "jaraco-collections==3.5.1",
                    ]
                )
                """
            )
        )

    # Via: jaraco-collections==3.5.1 -> jaraco-text -> inflect -> pydantic>=1.9.1
    # Pydantic 2.0 can get pulled in which defeats the Pip legacy resolver and leads to a resolve
    # conflict for PyPy; so we bound pydantic low.
    constraints = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints, "w") as fp:
        fp.write("pydantic<2")

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex_args = [
        "--pex-root",
        pex_root,
        "--runtime-pex-root",
        pex_root,
        src,
        "--constraints",
        constraints,
        "--resolver-version",
        "pip-2020-resolver",
        "--",
        "-c",
        "from jaraco import collections; print(collections.__file__)",
    ]
    old_result = run_pex_command(
        args=["pex==2.1.80", "-c", "pex", "--"] + pex_args,
        # N.B.: Pex 2.1.80 only works on CPython 3.10 and older and PyPy 3.7 and older.
        python=py310.binary if PY_VER > (3, 10) or (IS_PYPY and PY_VER > (3, 7)) else None,
    )
    old_result.assert_failure()
    assert (
        "Failed to resolve compatible distributions:\n"
        "1: pex-test==0.1 requires jaraco-collections==3.5.1 but jaraco.collections 3.5.1 was "
        "resolved" in old_result.error
    )

    new_result = run_pex_command(args=pex_args)
    new_result.assert_success()
    assert new_result.output.startswith(pex_root)
