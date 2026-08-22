# coding=utf-8
# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.compatibility import to_unicode
from pex.dist_metadata import ProjectNameAndVersion
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import IS_PYPY, WheelBuilder
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Text


def assert_bin_sh_shebang(
    venv,  # type: Virtualenv
    script,  # type: str
):
    # type: (...) -> None
    with open(venv.bin_path(script), "rb") as fp:
        assert b"#!/bin/sh\n" == fp.readline()


def assert_undill_venv_repository_from(
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


# N.B.: This covers Linux in standard configurations (generally 255) as well as macOS (511).
MAX_SHEBANG_LENGTH = 512


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


skip_if_uv_not_supported = pytest.mark.skipif(
    sys.version_info < (3, 8), reason="Use of uv is required and uv only supports Python >= 3.8."
)
skip_for_pypy = pytest.mark.skipif(IS_PYPY, reason="The `undill` script does not work with PyPy.")


@skip_if_uv_not_supported
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

    assert_bin_sh_shebang(uv_venv, script="undill")
    assert_undill_venv_repository_from(tmpdir, uv_venv)


@skip_for_pypy
def test_pip_too_long_data_scripts_shebang(tmpdir):
    pip_venv_dir = create_too_long_venv_dir(tmpdir)
    pip_venv = Virtualenv.create(venv_dir=pip_venv_dir, install_pip=InstallationChoice.YES)
    pip_venv.interpreter.execute(args=["-m", "pip", "install", "dill"])

    # N.B.: As of this writing no version of Pip re-writes #!python in data scripts using a
    # `#!/bin/sh` re-director script: https://github.com/pypa/pip/issues/13389
    # As such, we do not `assert_bin_sh_shebang`.
    assert_undill_venv_repository_from(tmpdir, pip_venv)


@skip_for_pypy
def test_pex_too_long_data_scripts_shebang(tmpdir):
    pex_root = tmpdir.join("pex-root")
    pex_venv_dir = create_too_long_venv_dir(tmpdir)
    run_pex3("venv", "create", "--pex-root", pex_root, "-d", pex_venv_dir, "dill").assert_success()

    pex_venv = Virtualenv(pex_venv_dir)
    assert_bin_sh_shebang(pex_venv, script="undill")
    assert_undill_venv_repository_from(tmpdir, pex_venv)


@pytest.fixture
def custom_script_wheel(tmpdir):
    # type: (Tempdir) -> str

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "script"), "wb") as fp:
        # The \x80\x99 in windows-1252 are <euro><trademark>; i.e.: €™
        # These bytes are picked since they differ in UTF-8 and are <PAD><SGCI> there; i.e.:
        # non-printing characters.
        fp.write(b"#!python\n" b"# coding=windows-1252\n")
        fp.write(b'print("\x80\x99"')
        if sys.version_info[0] == 2:
            fp.write(b'.decode("windows-1252").encode("utf-8")')
        fp.write(b")\n")

    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup()
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = custom_encoding_data_script
                version = 0.1.0

                [options]
                scripts = script
                """
            )
        )
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                build-backend = "setuptools.build_meta"
                requires = ["setuptools"]
                """
            )
        )
    return WheelBuilder(project_dir).bdist()


@pytest.fixture
def custom_script_requirement(custom_script_wheel):
    # type: (str) -> Text
    return ProjectNameAndVersion.from_filename(custom_script_wheel).project_name


def assert_custom_script_works(venv):
    # type: (Virtualenv) -> None
    assert to_unicode("€™\n") == subprocess.check_output(args=[venv.bin_path("script")]).decode(
        "utf-8"
    )


def assert_custom_script_repository_from(
    tmpdir,  # type: Tempdir
    venv,  # type: Virtualenv
    custom_script_requirement,  # type: str
):
    # type: (...) -> None

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
        custom_script_requirement,
    ).assert_success()

    pex_venv = Virtualenv(pex_venv_dir)
    assert_custom_script_works(pex_venv)
    shutil.rmtree(venv.venv_dir)
    assert_custom_script_works(pex_venv)


@skip_if_uv_not_supported
def test_uv_too_long_data_scripts_shebang_custom_script_encoding(
    tmpdir,  # type: Tempdir
    custom_script_wheel,  # type: str
    custom_script_requirement,  # type: str
):
    # type: (...) -> None

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
        args=["uv", "pip", "install", "--python", uv_venv.interpreter.binary, custom_script_wheel]
    )

    assert_bin_sh_shebang(uv_venv, script="script")

    # N.B.: We do not `assert_custom_script_works(uv_venv) because uv incorrectly maps:
    # ---
    # #!python
    # # coding=XXX
    # ---
    # To:
    # ---
    # #!/bin/sh
    # '''exec' ...
    # '''
    # # coding=XXX
    # ---
    # In other words - it does not put the `# coding=XXX` line 2nd after the shebang - which is
    # required for Python to read it and interpret the script Python code using the XXX encoding.

    assert_custom_script_repository_from(tmpdir, uv_venv, custom_script_requirement)


def test_pip_too_long_data_scripts_shebang_custom_script_encoding(
    tmpdir,  # type: Tempdir
    custom_script_wheel,  # type: str
    custom_script_requirement,  # type: str
):
    pip_venv_dir = create_too_long_venv_dir(tmpdir)
    pip_venv = Virtualenv.create(venv_dir=pip_venv_dir, install_pip=InstallationChoice.YES)
    pip_venv.interpreter.execute(args=["-m", "pip", "install", custom_script_wheel])

    # N.B.: As of this writing no version of Pip re-writes #!python in data scripts using a
    # `#!/bin/sh` re-director script: https://github.com/pypa/pip/issues/13389
    # As such, we do not `assert_bin_sh_shebang(pip_venv)` or
    # `assert_custom_script_works(pip_venv)`.

    assert_custom_script_repository_from(tmpdir, pip_venv, custom_script_requirement)


def test_pex_too_long_data_scripts_shebang_custom_script_encoding(
    tmpdir,  # type: Tempdir
    custom_script_wheel,  # type: str
    custom_script_requirement,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex_venv_repository_dir = create_too_long_venv_dir(tmpdir)
    run_pex3(
        "venv", "create", "--pex-root", pex_root, "-d", pex_venv_repository_dir, custom_script_wheel
    ).assert_success()

    pex_venv_repository = Virtualenv(pex_venv_repository_dir)
    assert_bin_sh_shebang(pex_venv_repository, script="script")
    assert_custom_script_works(pex_venv_repository)
    assert_custom_script_repository_from(tmpdir, pex_venv_repository, custom_script_requirement)
