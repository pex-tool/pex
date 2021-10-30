# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys

import pytest

from pex.layout import Layout
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.parametrize(
    "strip_pex_env", [pytest.param(True, id="StripPexEnv"), pytest.param(False, id="NoStripPexEnv")]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize("venv", [pytest.param(True, id="VENV"), pytest.param(False, id="UNZIP")])
def test_pex_variable_always_defined_at_runtime(
    tmpdir,  # type: Any
    strip_pex_env,  # type: bool
    venv,  # type: bool
    layout,  # type: Layout.Value
    pex_bdist,  # type: str
):
    # type: (...) -> None
    pex_pex = os.path.join(str(tmpdir), "pex.pex")

    build_pex_args = [
        pex_bdist,
        "--layout",
        layout.value,
        "--strip-pex-env" if strip_pex_env else "--no-strip-pex-env",
        "-o",
        pex_pex,
    ]
    if venv:
        build_pex_args.append("--venv")

    run_pex_command(args=build_pex_args).assert_success()

    run_pex_args = [pex_pex] if Layout.ZIPAPP == layout else [sys.executable, pex_pex]
    assert (
        os.path.realpath(pex_pex)
        == subprocess.check_output(
            args=run_pex_args + ["-c", "from pex.variables import ENV; print(ENV.PEX)"]
        )
        .decode("utf-8")
        .strip()
    )
