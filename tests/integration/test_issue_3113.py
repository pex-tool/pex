# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os.path
import shutil
import subprocess
from typing import Tuple

import pytest

from pex.common import safe_delete
from pex.util import CacheHelper
from testing import (
    IS_LINUX_X86_64,
    PyenvPythonDistribution,
    ensure_python_distribution,
    make_env,
    run_pex_command,
)
from testing.pytest_utils.tmp import Tempdir


@pytest.fixture
def cowsay(tmpdir):
    # type: (Tempdir) -> str

    pex_root = tmpdir.join("pex-root")
    cowsay = tmpdir.join("cowsay.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "cowsay<6",
            "-c",
            "cowsay",
            "-o",
            cowsay,
        ]
    ).assert_success()
    return cowsay


def pypy_dist(
    pyenv_version,  # type: str
    python_version,  # type: Tuple[int, int, int]
):
    # type: (...) -> PyenvPythonDistribution
    pypy_distribution = ensure_python_distribution(
        pyenv_version,
        python_version="{major}.{minor}".format(major=python_version[0], minor=python_version[1]),
        allow_adhoc_version=True,
    )
    assert (
        "{major}.{minor}.{patch}".format(
            major=python_version[0], minor=python_version[1], patch=python_version[2]
        )
        == subprocess.check_output(
            args=[
                pypy_distribution.binary,
                "-c",
                "import sys; print('.'.join(map(str, sys.version_info[:3])))",
            ]
        )
        .decode("utf-8")
        .strip()
    )
    return pypy_distribution


@pytest.fixture
def pypy3_11_11_dist():
    # type: () -> PyenvPythonDistribution
    return pypy_dist("pypy3.11-7.3.19", python_version=(3, 11, 11))


@pytest.fixture
def pypy3_11_13_dist():
    # type: () -> PyenvPythonDistribution
    return pypy_dist("pypy3.11-7.3.20", python_version=(3, 11, 13))


@pytest.mark.skipif(
    not IS_LINUX_X86_64,
    reason=(
        "We only need to test this for one known-good pair of interpreters with matching binary "
        "hash and differing patch versions. The pypy3.11-7.3.19 / pypy3.11-7.3.20 pair is known to "
        "meet this criteria for x86_64 Linux."
    ),
)
def test_interpreter_upgrade_same_binary_hash(
    tmpdir,  # type: Tempdir
    cowsay,  # type: str
    pypy3_11_11_dist,  # type: PyenvPythonDistribution
    pypy3_11_13_dist,  # type: PyenvPythonDistribution
):
    # type: (...) -> None

    assert pypy3_11_11_dist.binary != pypy3_11_13_dist.binary
    assert CacheHelper.hash(pypy3_11_11_dist.binary) == CacheHelper.hash(pypy3_11_13_dist.binary)

    pypy_311_prefix = tmpdir.join("opt", "pypy")

    def install_pypy_311_and_create_venv(
        pypy_distribution,  # type: PyenvPythonDistribution
        venv_dir,  # type: str
    ):
        # type: (...) -> str

        if os.path.exists(pypy_311_prefix):
            shutil.move(pypy_311_prefix, pypy_311_prefix + ".sav")
        shutil.copytree(pypy_distribution.interpreter.prefix, pypy_311_prefix)
        for binary in glob.glob(os.path.join(pypy_311_prefix, "bin", "*")):
            if os.path.basename(binary) not in ("libpypy3.11-c.so", "pypy3.11"):
                safe_delete(binary)
        pypy_binary = os.path.join(pypy_311_prefix, "bin", "pypy3.11")
        venv_path = tmpdir.join(venv_dir)
        subprocess.check_call(args=[pypy_binary, "-m", "venv", venv_path])
        return os.path.join(venv_path, "bin", "python")

    pypy3_11_11_venv_binary = install_pypy_311_and_create_venv(pypy3_11_11_dist, "pypy3_11_11.venv")
    assert b"| I am 3.11.11 |" in subprocess.check_output(
        args=[pypy3_11_11_venv_binary, cowsay, "I am 3.11.11"],
        env=make_env(PEX_PYTHON_PATH=pypy3_11_11_venv_binary),
    )

    pypy3_11_13_venv_binary = install_pypy_311_and_create_venv(pypy3_11_13_dist, "pypy3_11_13.venv")
    assert b"| I am 3.11.13 |" in subprocess.check_output(
        args=[pypy3_11_13_venv_binary, cowsay, "I am 3.11.13"],
        env=make_env(PEX_PYTHON_PATH=pypy3_11_13_venv_binary),
    )
