# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
import sys
from subprocess import CalledProcessError

import pytest

from pex.cache.dirs import CacheDir
from pex.layout import Layout
from pex.pep_427 import InstallableType
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pep_427 import get_installable_type_flag

if TYPE_CHECKING:
    from typing import Any, Callable, Dict, Iterable, Tuple

    import attr  # vendor:skip

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
    extra_args = attr.ib()  # type: Iterable[str]
    isort_code_dir = attr.ib()  # type: Callable[[Layout.Value, InstallableType.Value], str]
    venv_exception_expected = attr.ib()  # type: bool


def installed_wheels_or_deps(
    layout,  # type: Layout.Value
    installable_type,  # type: InstallableType.Value
):
    # type: (...) -> str
    return (
        "{app_root}/.deps/"
        if layout is Layout.LOOSE and installable_type is InstallableType.INSTALLED_WHEEL_CHROOT
        else "{pex_root}/installed_wheels/"
    )


@pytest.mark.parametrize(
    "execution_mode",
    [
        pytest.param(
            ExecutionMode(
                extra_args=[],
                isort_code_dir=installed_wheels_or_deps,
                venv_exception_expected=True,
            ),
            id="PEX",
        ),
        pytest.param(
            ExecutionMode(
                extra_args=["--include-tools"],
                isort_code_dir=installed_wheels_or_deps,
                venv_exception_expected=False,
            ),
            id="PEX --include-tools",
        ),
        pytest.param(
            ExecutionMode(
                extra_args=["--venv"],
                isort_code_dir=lambda _, __: "{pex_root}/venvs/",
                venv_exception_expected=False,
            ),
            id="VENV",
        ),
    ],
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
def test_execution_mode(
    create_colors_pex,  # type: CreateColorsPex
    execute_colors_pex,  # type: ExecuteColorsPex
    execution_mode,  # type: ExecutionMode
    layout,  # type: Layout.Value
    installable_type,  # type: InstallableType.Value
):
    # type: (...) -> None
    pex_app = create_colors_pex(
        list(execution_mode.extra_args)
        + ["--layout", layout.value, get_installable_type_flag(installable_type)]
    )

    output, pex_root = execute_colors_pex(pex_app, {})
    assert output.startswith(
        execution_mode.isort_code_dir(layout, installable_type).format(
            app_root=pex_app, pex_root=pex_root
        ),
    )

    if execution_mode.venv_exception_expected:
        with pytest.raises(CalledProcessError):
            execute_colors_pex(pex_app, {"PEX_VENV": "1"})
    else:
        output, pex_root = execute_colors_pex(pex_app, {"PEX_VENV": "1"})
        assert output.startswith(CacheDir.VENVS.path(pex_root=pex_root))
