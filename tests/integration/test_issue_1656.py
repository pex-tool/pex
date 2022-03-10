# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys

import pytest

from pex.interpreter import PythonInterpreter
from pex.pex_info import PexInfo
from pex.testing import make_env, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List, Text


def create_pex_pex(
    pex_version,  # type: str
    pex_file,  # type: str
):
    # type: (...) -> None

    run_pex_command(
        args=["pex=={pex_version}".format(pex_version=pex_version), "-c", "pex", "-o", pex_file]
    ).assert_success()


@pytest.fixture(scope="module")
def old_pex(tmpdir_factory):
    # type: (Any) -> str

    # This was the first version to support Python 3.10, and it did not rely upon the RECORD file to
    # build venvs.
    pex_version = "2.1.55"
    pex_file = os.path.join(str(tmpdir_factory.mktemp(pex_version)), "tool.pex")
    create_pex_pex(pex_version=pex_version, pex_file=pex_file)
    return pex_file


def run_current_pex_tool(
    subject_pex,  # type: str
    subcommand,  # type: str
    *args  # type: str
):
    # type: (...) -> Text

    return subprocess.check_output(
        args=[sys.executable, "-m", "pex.tools", subject_pex, subcommand] + list(args)
    ).decode("utf-8")


def run_pex_tool(
    pex_pex,  # type: str
    subject_pex,  # type: str
    subcommand,  # type: str
    *args  # type: str
):
    # type: (...) -> Text
    return subprocess.check_output(
        args=[pex_pex, subject_pex, subcommand] + list(args), env=make_env(PEX_MODULE="pex.tools")
    ).decode("utf-8")


def test_old_venv_tool_vs_new_pex(
    tmpdir,  # type: Any
    old_pex,  # type: str
):
    # type: (...) -> None

    pex_app = os.path.join(str(tmpdir), "app.pex")
    run_pex_command(args=["cowsay==4.0", "-c" "cowsay", "-o", pex_app]).assert_success()

    venv = os.path.join(str(tmpdir), "venv")
    run_pex_tool(old_pex, pex_app, "venv", "--force", venv)
    assert b"4.0\n" == subprocess.check_output(args=[os.path.join(venv, "pex"), "--version"])


def test_new_venv_tool_vs_old_pex(
    tmpdir,  # type: Any
    old_pex,  # type: str
):
    # type: (...) -> None

    pex_app = os.path.join(str(tmpdir), "app.pex")
    subprocess.check_call(args=[old_pex, "cowsay==4.0", "-c" "cowsay", "-o", pex_app])

    venv = os.path.join(str(tmpdir), "venv")
    run_current_pex_tool(pex_app, "venv", "--force", venv)
    assert b"4.0\n" == subprocess.check_output(args=[os.path.join(venv, "pex"), "--version"])


def test_mixed_pex_root(
    tmpdir,  # type: Any
    old_pex,  # type: str
    py37,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    def create_pex_args(*args):
        # type: (*str) -> List[str]

        # N.B.: We use --intransitive here + PEX_IGNORE_ERRORS=True below to avoid resolving the
        # full selenium dependency set, which is large. We can test greenlet's unique layout +
        # import and also test that selenium's absolute path RECORD entries don't trip us up with
        # just this and no more, proving out the particular bugged cases in #1656.
        return list(args) + [
            "--python",
            py37.binary,
            "--python",
            sys.executable,
            "--venv",
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--intransitive",
            "greenlet==1.1.2",
            "selenium==4.1.2; python_version >= '3.7'",
        ]

    def greenlet_include_venv_path(venv_dir):
        # type: (str) -> str
        return os.path.join(venv_dir, "include", "site", "python3.7", "greenlet", "greenlet.h")

    pex_app_old = os.path.join(str(tmpdir), "app.old.pex")
    subprocess.check_call(args=create_pex_args(old_pex, "-o", pex_app_old))

    pex_app_new = os.path.join(str(tmpdir), "app.new.pex")
    run_pex_command(args=create_pex_args("-o", pex_app_new, "--venv")).assert_success()

    subprocess.check_call(
        args=[sys.executable, pex_app_old, "-c", "import greenlet"],
        env=make_env(PEX_IGNORE_ERRORS=True, PEX_VENV=False),
    )
    subprocess.check_call(
        args=[sys.executable, pex_app_new, "-c", "import greenlet"],
        env=make_env(PEX_IGNORE_ERRORS=True, PEX_VENV=False),
    )
    subprocess.check_call(
        args=[sys.executable, pex_app_old, "-c", "import greenlet"],
        env=make_env(PEX_IGNORE_ERRORS=True),
    )
    subprocess.check_call(
        args=[sys.executable, pex_app_new, "-c", "import greenlet"],
        env=make_env(PEX_IGNORE_ERRORS=True),
    )

    py37_venv_dir_old = PexInfo.from_pex(pex_app_new).venv_dir(pex_app_old, py37)
    assert py37_venv_dir_old is not None
    assert not os.path.exists(py37_venv_dir_old)

    subprocess.check_call(
        args=[py37.binary, pex_app_old, "-c", "import greenlet"],
        env=make_env(PEX_IGNORE_ERRORS=True),
    )
    assert not os.path.exists(greenlet_include_venv_path(py37_venv_dir_old))

    py37_venv_dir_new = PexInfo.from_pex(pex_app_new).venv_dir(pex_app_new, py37)
    assert py37_venv_dir_new is not None
    assert not os.path.exists(py37_venv_dir_new)

    subprocess.check_call(
        args=[py37.binary, pex_app_new, "-c", "import greenlet"],
        env=make_env(PEX_IGNORE_ERRORS=True),
    )
    assert os.path.exists(greenlet_include_venv_path(py37_venv_dir_new))
