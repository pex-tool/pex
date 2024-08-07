# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

import colors  # vendor:skip
import pytest

from pex.inherit_path import InheritPath
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import PY_VER, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.parametrize(
    "inherit_path",
    [pytest.param(inherit_path, id=inherit_path.value) for inherit_path in InheritPath.values()],
)
def test_inherit_path_pex_info(
    tmpdir,  # type: Any
    inherit_path,  # type: InheritPath.Value
):
    # type: (...) -> None

    venv_dir = os.path.join(str(tmpdir), "venv")
    run_pex_command(
        args=["ansicolors==1.1.8", "--include-tools", "--", "venv", venv_dir],
        env=make_env(PEX_TOOLS=1),
    ).assert_success()
    venv_python = Virtualenv(venv_dir).interpreter.binary

    def assert_inherit_path(
        pex,  # type: str
        **env  # type: Any
    ):
        # type: (...) -> None

        expect_success = inherit_path is not InheritPath.FALSE
        process = subprocess.Popen(
            args=[venv_python, pex, "-c", "import colors; print(colors.yellow('Babel Fish'))"],
            env=make_env(**env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        if expect_success:
            assert process.returncode == 0, stderr
            assert colors.yellow("Babel Fish") == stdout.decode("utf-8").strip()
        else:
            assert process.returncode != 0
            assert (
                "ImportError: No module named colors"
                if PY_VER == (2, 7)
                else "ModuleNotFoundError: No module named 'colors'"
            ) in stderr.decode("utf-8")

    empty_pex_build_time = os.path.join(str(tmpdir), "empty-build-time.pex")
    run_pex_command(
        args=["--inherit-path={value}".format(value=inherit_path.value), "-o", empty_pex_build_time]
    ).assert_success()
    assert_inherit_path(empty_pex_build_time)

    empty_pex_run_time = os.path.join(str(tmpdir), "empty-run-time.pex")
    run_pex_command(args=["-o", empty_pex_run_time]).assert_success()
    assert_inherit_path(empty_pex_run_time, PEX_INHERIT_PATH=inherit_path)
