# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
import sys
from subprocess import CalledProcessError

import pytest

from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr
    from typing import Any, Callable, Dict, Iterable, Tuple

    CreateColorsPex = Callable[[Iterable[str]], str]
    ExecuteColorsPex = Callable[[str, Dict[str, str]], Tuple[str, str]]
else:
    from pex.third_party import attr


@pytest.fixture
def create_colors_pex(tmpdir):
    # type: (Any) -> CreateColorsPex
    def create(extra_args):
        pex_file = os.path.join(str(tmpdir), "colors.pex")
        results = run_pex_command(["ansicolors==1.1.8", "-o", pex_file] + list(extra_args))
        results.assert_success()
        return pex_file

    return create


@pytest.fixture
def execute_colors_pex(tmpdir):
    # type: (Any) -> ExecuteColorsPex
    def execute(colors_pex, extra_env):
        pex_root = os.path.join(str(tmpdir), "pex_root")
        env = os.environ.copy()
        env.update(extra_env)
        env["PEX_ROOT"] = pex_root
        args = [colors_pex] if os.path.isfile(colors_pex) else [sys.executable, colors_pex]
        output = subprocess.check_output(
            args=args + ["-c", "import colors; print(colors.__file__)"], env=env
        )
        return output.strip().decode("utf-8"), pex_root

    return execute


@attr.s(frozen=True)
class ExecutionMode(object):
    default_isort_code_dir = attr.ib()  # type: str
    extra_args = attr.ib(default=())  # type: Iterable[str]
    unzipped_isort_code_dir = attr.ib(default="unzipped_pexes")  # type: str
    venv_exception_expected = attr.ib(default=True)  # type: bool


@pytest.mark.parametrize(
    ["execution_mode"],
    [
        pytest.param(ExecutionMode(default_isort_code_dir="installed_wheels"), id="ZIPAPP"),
        pytest.param(
            ExecutionMode(
                extra_args=["--include-tools"],
                default_isort_code_dir="installed_wheels",
                venv_exception_expected=False,
            ),
            id="ZIPAPP --include-tools",
        ),
        pytest.param(
            ExecutionMode(extra_args=["--unzip"], default_isort_code_dir="unzipped_pexes"),
            id="UNZIP",
        ),
        pytest.param(
            ExecutionMode(
                extra_args=["--unzip", "--include-tools"],
                default_isort_code_dir="unzipped_pexes",
                venv_exception_expected=False,
            ),
            id="UNZIP --include-tools",
        ),
        pytest.param(
            ExecutionMode(
                extra_args=["--venv"], default_isort_code_dir="venvs", venv_exception_expected=False
            ),
            id="VENV",
        ),
        pytest.param(
            ExecutionMode(
                extra_args=["--spread"],
                default_isort_code_dir="installed_wheels",
                unzipped_isort_code_dir="installed_wheels",
            ),
            id="Spread",
        ),
        pytest.param(
            ExecutionMode(
                extra_args=["--spread", "--include-tools"],
                default_isort_code_dir="installed_wheels",
                unzipped_isort_code_dir="installed_wheels",
                venv_exception_expected=False,
            ),
            id="Spread --include-tools",
        ),
        pytest.param(
            ExecutionMode(
                extra_args=["--venv", "--spread"],
                default_isort_code_dir="venvs",
                unzipped_isort_code_dir="installed_wheels",
                venv_exception_expected=False,
            ),
            id="Spread VENV",
        ),
    ],
)
def test_execution_mode(
    create_colors_pex,  # type: CreateColorsPex
    execute_colors_pex,  # type: ExecuteColorsPex
    execution_mode,  # type: ExecutionMode
):
    # type: (...) -> None
    pex_file = create_colors_pex(execution_mode.extra_args)

    output, pex_root = execute_colors_pex(pex_file, {})
    assert output.startswith(os.path.join(pex_root, execution_mode.default_isort_code_dir))

    output, pex_root = execute_colors_pex(pex_file, {"PEX_UNZIP": "1"})
    assert output.startswith(os.path.join(pex_root, execution_mode.unzipped_isort_code_dir))

    if execution_mode.venv_exception_expected:
        with pytest.raises(CalledProcessError):
            execute_colors_pex(pex_file, {"PEX_VENV": "1"})
    else:
        output, pex_root = execute_colors_pex(pex_file, {"PEX_VENV": "1"})
        assert output.startswith(os.path.join(pex_root, "venvs"))
