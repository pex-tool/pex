# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.interpreter import MAX_SHEBANG_LENGTH
from pex.typing import cast
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import IS_PYPY
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


def assert_bin_sh_shebang(venv):
    # type: (Virtualenv) -> None
    with open(venv.bin_path("undill")) as fp:
        assert "#!/bin/sh\n" == fp.readline()


def assert_venv_repository_from(
    tmpdir,  # type: Tempdir
    venv,  # type: Virtualenv
):
    pickled = tmpdir.join("hello.pkl")
    venv.interpreter.execute(
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
        venv.venv_dir,
        "--pre",
        "dill",
    ).assert_success()

    pex_venv = Virtualenv(pex_venv_dir)

    def assert_undill_works():
        assert b"['hello', 'world']\n" == subprocess.check_output(
            args=[(pex_venv.bin_path("undill")), pickled]
        )

    assert_undill_works()
    shutil.rmtree(venv.venv_dir)
    assert_undill_works()


def create_too_long_venv_dir(tmpdir):
    # type: (...) -> str
    venv_dir = tmpdir.join("venv", "too-long")
    while len(venv_dir) < MAX_SHEBANG_LENGTH:
        # N.B.: Instead of adding one extra directory to make up the remaining length needed to
        # break MAX_SHEBANG_LENGTH, we limit directory names to 127 characters to not run afoul of
        # max filename lengths in the process. The 127 is chosen at ~1/2 255 which is the expected
        # real limit on both Linux and macOS.
        extra = min(127, max(1, MAX_SHEBANG_LENGTH - len(venv_dir)))
        venv_dir = os.path.join(venv_dir, "x" * extra)
    assert len(venv_dir) > MAX_SHEBANG_LENGTH
    return cast(str, venv_dir)


skip_for_pypy = pytest.mark.skipif(IS_PYPY, reason="The `undill` script does not work with PyPy.")


@pytest.mark.skipif(
    sys.version_info < (3, 8), reason="Use of uv is required and uv only supports Python >= 3.8."
)
@skip_for_pypy
def test_uv_too_long_data_scripts_shebang(tmpdir):
    # type: (Tempdir) -> None

    uv_venv_dir = create_too_long_venv_dir(tmpdir)
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

    assert_bin_sh_shebang(uv_venv)
    assert_venv_repository_from(tmpdir, uv_venv)


@skip_for_pypy
def test_pip_too_long_data_scripts_shebang(tmpdir):
    pip_venv_dir = create_too_long_venv_dir(tmpdir)
    pip_venv = Virtualenv.create(venv_dir=pip_venv_dir, install_pip=InstallationChoice.YES)
    pip_venv.interpreter.execute(args=["-m", "pip", "install", "dill"])

    # N.B.: As of this writing no version of Pip re-writes #!python in data scripts using a
    # `#!/bin/sh` re-director script: https://github.com/pypa/pip/issues/13389
    # As such, we do not `assert_bin_sh_shebang`.
    assert_venv_repository_from(tmpdir, pip_venv)


@skip_for_pypy
def test_pex_too_long_data_scripts_shebang(tmpdir):
    pex_root = tmpdir.join("pex-root")
    pex_venv_dir = create_too_long_venv_dir(tmpdir)
    run_pex3("venv", "create", "--pex-root", pex_root, "-d", pex_venv_dir, "dill").assert_success()

    pex_venv = Virtualenv(pex_venv_dir)
    assert_bin_sh_shebang(pex_venv)
    assert_venv_repository_from(tmpdir, pex_venv)
