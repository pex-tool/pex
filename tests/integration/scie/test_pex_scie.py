# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import subprocess

import pytest

from pex.layout import Layout
from pex.scie import ScieStyle
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any, List


@pytest.mark.parametrize(
    "scie_style", [pytest.param(style, id=str(style)) for style in ScieStyle.values()]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=str(layout)) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--sh-boot"], id="ZIPAPP-sh-boot"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-sh-boot"),
    ],
)
def test_basic(
    tmpdir,  # type: Any
    scie_style,  # type: ScieStyle.Value
    layout,  # type: Layout.Value
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "cowsay.pex")
    result = run_pex_command(
        args=[
            "cowsay==5.0",
            "-c",
            "cowsay",
            "-o",
            pex,
            "--scie",
            str(scie_style),
            "--layout",
            str(layout),
        ]
        + execution_mode_args
    )
    if PY_VER < (3, 8) or IS_PYPY:
        result.assert_failure(
            expected_error_re=r".*^{message}$".format(
                message=re.escape(
                    "You selected `--scie {style}`, but none of the selected targets have "
                    "compatible interpreters that can be embedded to form a scie:\n"
                    "{target}".format(
                        style=scie_style, target=LocalInterpreter.create().render_description()
                    )
                )
            ),
            re_flags=re.DOTALL | re.MULTILINE,
        )
        return
    if PY_VER >= (3, 13):
        result.assert_failure(
            expected_error_re=(
                r".*"
                r"^Failed to build 1 scie:$"
                r".*"
                r"^Provider: No released assets found for release [0-9]{{8}} Python {version} "
                r"of flavor install_only\.$".format(version=".".join(map(str, PY_VER)))
            ),
            re_flags=re.DOTALL | re.MULTILINE,
        )
        return
    result.assert_success()

    scie = os.path.join(str(tmpdir), "cowsay")
    assert b"| PAR! |" in subprocess.check_output(args=[scie, "PAR!"], env=make_env(PATH=None))
