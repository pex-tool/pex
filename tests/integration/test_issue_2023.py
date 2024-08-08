# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest
from colors import colors  # vendor:skip

from pex.layout import Layout
from pex.pep_427 import InstallableType
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pep_427 import get_installable_type_flag

if TYPE_CHECKING:
    from typing import Any, List


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
@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="UNZIP"),
        pytest.param(["--venv", "--venv-site-packages-copies"], id="VENV (copies)"),
        pytest.param(["--venv", "--no-venv-site-packages-copies"], id="VENV (symlinks)"),
    ],
)
def test_unpack_robustness(
    tmpdir,  # type: Any
    layout,  # type: Layout.Value
    installable_type,  # type: InstallableType.Value
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None
    exe = os.path.join(str(tmpdir), "exe.py")
    with open(exe, "w") as fp:
        fp.write(
            dedent(
                """\
                import colors

                print(colors.cyan("Wowbagger hasn't gotten to me yet."))
                """
            )
        )

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex_command(
        args=[
            "--runtime-pex-root",
            pex_root,
            "ansicolors==1.1.8",
            "--exe",
            exe,
            "--layout",
            layout.value,
            get_installable_type_flag(installable_type),
            "-o",
            pex,
        ]
        + execution_mode_args
    ).assert_success()

    def assert_pex_works(pex_path):
        # type: (str) -> None
        assert (
            colors.cyan("Wowbagger hasn't gotten to me yet.")
            == subprocess.check_output(args=[sys.executable, pex_path]).decode("utf-8").strip()
        )

    assert_pex_works(pex)

    elsewhere = os.path.join(str(tmpdir), "elsewhere")
    os.mkdir(elsewhere)
    dest = os.path.join(elsewhere, "other")
    shutil.move(pex, dest)
    assert_pex_works(dest)

    shutil.rmtree(pex_root)
    assert_pex_works(dest)
