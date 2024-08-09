# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess

import colors  # vendor:skip
import pytest

from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from testing import PY310, ensure_python_distribution, make_env, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Text

COWSAY_REQUIREMENT = "cowsay==6.0"
BLUE_MOO_ARGS = ["-c", "import colors; from cowsay import tux; tux(colors.cyan('Moo?'))"]


def assert_blue_moo(output):
    # type: (Text) -> None
    assert "| {moo} |".format(moo=colors.cyan("Moo?")) in output, output


def assert_colors_import_error(
    process,  # type: subprocess.Popen
    python=PythonInterpreter.get(),  # type: PythonInterpreter
):
    # type: (...) -> None
    _, stderr = process.communicate()
    assert 0 != process.returncode
    if python.version[0] == 2:
        assert b"ImportError: No module named colors\n" in stderr, stderr.decode("utf-8")
    else:
        assert b"ModuleNotFoundError: No module named 'colors'\n" in stderr, stderr.decode("utf-8")


@pytest.fixture
def system_python_with_colors(tmpdir):
    # type: (Any) -> str
    location, _, _, _ = ensure_python_distribution(PY310)
    system_python_distribution = os.path.join(str(tmpdir), "py310")
    shutil.copytree(location, system_python_distribution)
    system_python = os.path.join(system_python_distribution, "bin", "python")
    subprocess.check_call(args=[system_python, "-m", "pip", "install", "ansicolors==1.1.8"])
    return system_python


def test_system_site_packages_venv_pex(
    tmpdir,  # type: Any
    system_python_with_colors,  # type: str
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--venv",
            "--venv-system-site-packages",
            COWSAY_REQUIREMENT,
            "-o",
            pex,
        ]
    ).assert_success()
    assert_colors_import_error(subprocess.Popen(args=[pex] + BLUE_MOO_ARGS, stderr=subprocess.PIPE))

    shutil.rmtree(pex_root)
    assert_blue_moo(
        subprocess.check_output(args=[system_python_with_colors, pex] + BLUE_MOO_ARGS).decode(
            "utf-8"
        )
    )


def test_system_site_packages_pex_tools(
    tmpdir,  # type: Any
    system_python_with_colors,  # type: str
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["--include-tools", COWSAY_REQUIREMENT, "-o", pex]).assert_success()

    venv = os.path.join(str(tmpdir), "venv")
    subprocess.check_call(
        args=[system_python_with_colors, pex, "venv", venv], env=make_env(PEX_TOOLS=1)
    )
    assert_colors_import_error(subprocess.Popen(args=[pex] + BLUE_MOO_ARGS, stderr=subprocess.PIPE))

    shutil.rmtree(venv)
    subprocess.check_call(
        args=[system_python_with_colors, pex, "venv", "--system-site-packages", venv],
        env=make_env(PEX_TOOLS=1),
    )
    assert_blue_moo(
        subprocess.check_output(args=[os.path.join(venv, "pex")] + BLUE_MOO_ARGS).decode("utf-8")
    )


def test_system_site_packages_pex3_venv(
    tmpdir,  # type: Any
    system_python_with_colors,  # type: str
):
    # type: (...) -> None

    venv = os.path.join(str(tmpdir), "venv")
    venv_python = os.path.join(venv, "bin", "python")
    run_pex3(
        "venv", "create", "--python", system_python_with_colors, "-d", venv, COWSAY_REQUIREMENT
    ).assert_success()
    assert_colors_import_error(
        subprocess.Popen(args=[venv_python] + BLUE_MOO_ARGS, stderr=subprocess.PIPE),
        python=PythonInterpreter.from_binary(venv_python),
    )

    shutil.rmtree(venv)
    run_pex3(
        "venv",
        "create",
        "--python",
        system_python_with_colors,
        "-d",
        venv,
        COWSAY_REQUIREMENT,
        "--system-site-packages",
    ).assert_success()
    assert_blue_moo(subprocess.check_output(args=[venv_python] + BLUE_MOO_ARGS).decode("utf-8"))
