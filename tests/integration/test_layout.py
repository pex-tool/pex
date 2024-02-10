# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys

import pytest

from pex.common import safe_open, safe_rmtree
from pex.layout import Layout
from pex.pep_427 import InstallableType
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pep_427 import get_installable_type_flag

if TYPE_CHECKING:
    from typing import Any, List


@pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="PEX"), pytest.param(["--venv"], id="VENV")]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "installable_type",
    [
        pytest.param(installable_type, id=installable_type.value)
        for installable_type in InstallableType.values()
    ],
)
def test_resiliency(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    layout,  # type: Layout.Value
    installable_type,  # type: InstallableType.Value
):
    # type: (...) -> None
    src_dir = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src_dir, "exe.py"), "w") as fp:
        fp.write("import colors; print(colors.__version__)")

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex_app = os.path.join(str(tmpdir), "pex_app")

    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "ansicolors==1.1.8",
            "-D",
            src_dir,
            "-e",
            "exe",
            "-o",
            pex_app,
            "--layout",
            layout.value,
            get_installable_type_flag(installable_type),
        ]
        + execution_mode_args
    ).assert_success()

    def assert_exe(*args):
        # type: (*str) -> None
        output = subprocess.check_output(args=args)
        assert b"1.1.8\n" == output

    executable = pex_app if layout == Layout.ZIPAPP else os.path.join(pex_app, "__main__.py")
    assert_exe(sys.executable, pex_app)
    assert_exe(executable)

    safe_rmtree(pex_root)
    assert_exe(executable)
    assert_exe(sys.executable, pex_app)
