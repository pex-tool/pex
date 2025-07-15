# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from os import mkdir

import pytest

from pex.compatibility import commonpath
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Iterator, List


@pytest.fixture
def read_only_pex_root(tmpdir):
    # type: (Tempdir) -> Iterator[str]

    pex_root = tmpdir.join("pex-root")
    mkdir(pex_root)
    os.chmod(pex_root, 0o555)
    try:
        yield pex_root
    finally:
        os.chmod(pex_root, 755)


@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--sh-boot"], id="SH_BOOT"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-SH_BOOT"),
    ],
)
def test_tmp_pex_root(
    tmpdir,  # type: Tempdir
    read_only_pex_root,  # type: str
    fake_system_tmp_dir,  # type: str
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    run_pex_command(
        args=["ansicolors==1.1.8", "-o", pex, "--runtime-pex-root", read_only_pex_root]
        + execution_mode_args
    ).assert_success()

    colors_module = (
        subprocess.check_output(args=[pex, "-c", "import colors; print(colors.__file__)"])
        .decode("utf-8")
        .strip()
    )
    assert fake_system_tmp_dir == commonpath((fake_system_tmp_dir, colors_module))
    assert "--venv" in execution_mode_args or not os.path.exists(colors_module)
