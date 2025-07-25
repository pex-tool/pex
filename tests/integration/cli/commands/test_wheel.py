# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import COMPATIBLE_PYTHON_VERSIONS
from pex.os import LINUX, MAC, WINDOWS
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


@pytest.fixture
def requirements_txt(tmpdir):
    # type: (Tempdir) -> str
    with open(tmpdir.join("requirements.txt"), "w") as fp:
        fp.write(
            dedent(
                """\
                cowsay<6
                psutil==5.9.5
                """
            )
        )
    return fp.name


def assert_wheels(dest_dir):
    # type: (str) -> None

    # N.B.: This is currently tuned to cases in our CI setup and may need to change as we change
    # that.
    interpreter = PythonInterpreter.get()
    platform = interpreter.platform
    if interpreter.is_pypy or (LINUX and sys.version_info[:2] == (3, 5)):
        interpreter = PythonInterpreter.get()
        expected_psutil = "psutil-5.9.5-{tag}.whl".format(
            tag=str(
                next(
                    tag
                    for tag in interpreter.identity.supported_tags
                    if "manylinux" not in tag.platform
                )
            )
        )
    elif LINUX and sys.version_info[0] == 2:
        expected_psutil = "psutil-5.9.5-cp27-{abi}-manylinux2010_x86_64.whl".format(
            abi=platform.abi
        )
    elif LINUX and sys.version_info[:2] == (3, 5):
        expected_psutil = "psutil-5.9.5.tar.gz"
    elif LINUX and sys.version_info[:2] >= (3, 6):
        expected_psutil = (
            "psutil-5.9.5-cp36-abi3-"
            "manylinux_2_12_x86_64.manylinux2010_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64"
            ".whl"
        )
    elif MAC:
        if "arm64" in platform.platform:
            expected_psutil = "psutil-5.9.5-cp38-abi3-macosx_11_0_arm64.whl"
        else:
            expected_psutil = "psutil-5.9.5-cp36-abi3-macosx_10_9_x86_64.whl"
    elif WINDOWS:
        expected_psutil = "psutil-5.9.5-cp37-abi3-win_amd64.whl"
    else:
        assert False, "The current OS / arch / interpreter is not supported by this test."

    assert sorted(("cowsay-5.0-py2.py3-none-any.whl", expected_psutil)) == sorted(
        os.listdir(dest_dir)
    )


def test_wheel_via_pip(
    tmpdir,  # type: Tempdir
    requirements_txt,  # type: str
):
    # type: (...) -> None

    dest_dir = tmpdir.join("dest")
    run_pex3(
        "wheel", "--pip-version", "latest-compatible", "-r", requirements_txt, "-d", dest_dir
    ).assert_success()
    assert_wheels(dest_dir)


def test_wheel_via_pex_lock(
    tmpdir,  # type: Tempdir
    requirements_txt,  # type: str
):
    # type: (...) -> None

    lock = tmpdir.join("lock.json")
    run_pex3("lock", "create", "-r", requirements_txt, "--indent", "2", "-o", lock).assert_success()

    dest_dir = tmpdir.join("dest")
    run_pex3(
        "wheel", "--pip-version", "latest-compatible", "--lock", lock, "-d", dest_dir
    ).assert_success()
    assert_wheels(dest_dir)

    shutil.rmtree(dest_dir)
    run_pex3(
        "wheel", "cowsay", "--pip-version", "latest-compatible", "--lock", lock, "-d", dest_dir
    ).assert_success()
    assert ["cowsay-5.0-py2.py3-none-any.whl"] == os.listdir(dest_dir)


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8),
    reason="The uv export does not work correctly for Pythons older than it supports (3.8).",
)
def test_wheel_via_pylock(
    tmpdir,  # type: Tempdir
    requirements_txt,  # type: str
):
    # type: (...) -> None

    max_major, max_minor = max(
        (version.major, version.minor) for version in COMPATIBLE_PYTHON_VERSIONS
    )

    pyproject_toml = tmpdir.join("pyproject.toml")
    with open(pyproject_toml, "w") as fp:
        fp.write(
            dedent(
                """\
                [project]
                name = "example"
                version = "0.0.1"
                requires-python = ">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,<{max_plus_one}"
                dependencies = [
                    "cowsay<6",
                    "psutil==5.9.5",
                ]
                """
            ).format(
                max_plus_one="{major}.{minor_plus_one}".format(
                    major=max_major, minor_plus_one=max_minor + 1
                )
            )
        )

    pylock_toml = tmpdir.join("pylock.toml")
    subprocess.check_call(
        args=[
            "uv",
            "--directory",
            str(tmpdir),
            "export",
            "-q",
            "--no-emit-project",
            "-o",
            pylock_toml,
        ]
    )

    dest_dir = tmpdir.join("dest")
    run_pex3(
        "wheel", "--pip-version", "latest-compatible", "--pylock", pylock_toml, "-d", dest_dir
    ).assert_success()
    assert_wheels(dest_dir)


EXPECTED_SDEV_LOGGING_UTILS_WHL = "sdev_logging_utils-0.1-py{major}-none-any.whl".format(
    major=sys.version_info.major
)


def test_archive_subdir_via_pex_lock(tmpdir):
    # type: (Tempdir) -> None

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        (
            "sdev_logging_utils @ "
            "https://github.com/SerialDev/sdev_py_utils/archive/"
            "bd4d36a02d1beb062ef911796cc18aec0ab99885.zip#subdirectory=sdev_logging_utils"
        ),
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    dest_dir = tmpdir.join("dest")
    run_pex3(
        "wheel", "--pip-version", "latest-compatible", "--lock", lock, "-d", dest_dir
    ).assert_success()
    assert [EXPECTED_SDEV_LOGGING_UTILS_WHL] == os.listdir(dest_dir)


def test_vcs_subdir_via_pex_lock(tmpdir):
    # type: (Tempdir) -> None

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        (
            "git+https://github.com/SerialDev/sdev_py_utils"
            "@bd4d36a0#egg=sdev_logging_utils&subdirectory=sdev_logging_utils"
        ),
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()

    dest_dir = tmpdir.join("dest")
    run_pex3(
        "wheel", "--pip-version", "latest-compatible", "--lock", lock, "-d", dest_dir
    ).assert_success()
    assert [EXPECTED_SDEV_LOGGING_UTILS_WHL] == os.listdir(dest_dir)
