# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import shutil
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.venv.virtualenv import Virtualenv
from testing import IS_PYPY
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    IS_PYPY or sys.version_info < (3, 8),
    reason=(
        "Use of uv is required and uv only supports Python >= 3.8 and the `undill` script does not "
        "work with PyPy."
    ),
)
def test_uv_too_long_data_scripts_shebang(tmpdir):
    # type: (Tempdir) -> None

    uv_venv_dir = tmpdir.join("uv-venv", "too-long", "x" * max(1, 128 - len(tmpdir.path)))
    subprocess.check_call(
        args=[
            "uv",
            "venv",
            "--python",
            "{major}.{minor}".format(major=sys.version_info[0], minor=sys.version_info[1]),
            uv_venv_dir,
        ]
    )

    uv_venv = Virtualenv(uv_venv_dir)
    subprocess.check_call(
        args=["uv", "pip", "install", "--python", uv_venv.interpreter.binary, "dill"]
    )

    pickled = tmpdir.join("hello.pkl")
    uv_venv.interpreter.execute(
        args=[
            "-c",
            dedent(
                """\
                import dill


                with open({pickled!r}, "wb") as fp:
                    dill.dump(["hello", "world"], fp)
                """
            ).format(pickled=pickled),
        ]
    )

    pex_root = tmpdir.join("pex-root")
    pex_venv_dir = tmpdir.join("pex-venv")
    run_pex3(
        "venv",
        "create",
        "--pex-root",
        pex_root,
        "--dest-dir",
        pex_venv_dir,
        "--venv-repository",
        uv_venv_dir,
        "--pre",
        "dill",
    ).assert_success()

    pex_venv = Virtualenv(pex_venv_dir)

    def assert_undill_works():
        assert b"['hello', 'world']\n" == subprocess.check_output(
            args=[pex_venv.bin_path("undill"), pickled]
        )

    assert_undill_works()
    shutil.rmtree(uv_venv_dir)
    assert_undill_works()
