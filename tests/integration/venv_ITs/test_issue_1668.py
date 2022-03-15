# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess

from pex.testing import PY37, ensure_python_interpreter, make_env, pex_project_dir, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def assert_venv_runtime_env_vars_ignored_during_create(
    tmpdir,  # type: Any
    pex_venv,  # type: bool
):
    # type: (...) -> None

    pex_pex = os.path.join(str(tmpdir), "pex.pex")
    args = [pex_project_dir(), "-c", "pex", "-o", pex_pex, "--no-strip-pex-env", "--disable-cache"]
    if pex_venv:
        args.append("--venv")
    run_pex_command(args=args).assert_success()

    py37 = ensure_python_interpreter(PY37)
    pex_root = os.path.join(str(tmpdir), "pex_root")
    lock = os.path.join(str(tmpdir), "lock.json")
    subprocess.check_call(
        args=[
            py37,
            pex_pex,
            "lock",
            "create",
            "ansicolors==1.1.8",
            "-o",
            lock,
            "--pex-root",
            pex_root,
        ],
        env=make_env(PEX_SCRIPT="pex3"),
    )
    ansicolors_path = (
        subprocess.check_output(
            args=[
                py37,
                pex_pex,
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--lock",
                lock,
                "--",
                "-c",
                "import colors; print(colors.__file__)",
            ]
        )
        .decode("utf-8")
        .strip()
    )
    assert ansicolors_path.startswith(pex_root)


def test_venv_runtime_env_vars_ignored_during_create_nested(tmpdir):
    # type: (Any) -> None

    # N.B.: The venv being created here is the internal Pip venv Pex uses to execute Pip. It's that
    # venv that used to get PEX env vars like PEX_MODULE and PEX_SCRIPT sealed in at creation time.
    assert_venv_runtime_env_vars_ignored_during_create(tmpdir, pex_venv=False)


def test_venv_runtime_env_vars_ignored_during_create_top_level(tmpdir):
    assert_venv_runtime_env_vars_ignored_during_create(tmpdir, pex_venv=True)
