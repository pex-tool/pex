# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
from subprocess import CalledProcessError

import pytest

from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, Dict, Iterable, Tuple

    CreateColorsPex = Callable[[Iterable[str]], str]
    ExecuteColorsPex = Callable[[str, Dict[str, str]], Tuple[str, str]]


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
        output = subprocess.check_output(
            [colors_pex, "-c", "import colors; print(colors.__file__)"], env=env
        )
        return output.strip().decode("utf-8"), pex_root

    return execute


@pytest.mark.parametrize(
    ["extra_args", "default_dir", "venv_exception_expected"],
    [
        pytest.param([], "installed_wheels", True, id="ZIPAPP"),
        pytest.param(["--include-tools"], "installed_wheels", False, id="ZIPAPP --include-tools"),
        pytest.param(["--unzip"], "unzipped", True, id="UNZIP"),
        pytest.param(["--unzip", "--include-tools"], "unzipped", False, id="UNZIP --include-tools"),
        pytest.param(["--venv"], "venvs", False, id="VENV"),
    ],
)
def test_execution_mode(
    create_colors_pex,  # type: CreateColorsPex
    execute_colors_pex,  # type: ExecuteColorsPex
    extra_args,  # type: Iterable[str]
    default_dir,  # type: str
    venv_exception_expected,  # type: bool
):
    # type: (...) -> None
    pex_file = create_colors_pex(extra_args)

    output, pex_root = execute_colors_pex(pex_file, {})
    assert output.startswith(os.path.join(pex_root, default_dir))

    output, pex_root = execute_colors_pex(pex_file, {"PEX_UNZIP": "1"})
    assert output.startswith(os.path.join(pex_root, "unzipped"))

    if venv_exception_expected:
        with pytest.raises(CalledProcessError):
            execute_colors_pex(pex_file, {"PEX_VENV": "1"})
    else:
        output, pex_root = execute_colors_pex(pex_file, {"PEX_VENV": "1"})
        assert output.startswith(os.path.join(pex_root, "venvs"))
