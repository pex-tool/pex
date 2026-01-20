# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import subprocess
import sys

import colors  # vendor:skip
import pytest

from testing import IS_PYPY, data, run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_platform_placeholder_simple(tmpdir):
    # type: (Tempdir) -> None

    result = run_pex_command(
        args=["ansicolors==1.1.8", "-o", tmpdir.join("ansicolors-{platform}.pex")]
    )
    result.assert_success()

    pex = result.output.strip()
    assert tmpdir.join("ansicolors-py2.py3-none-any.pex") == pex
    assert (
        colors.blue("platform")
        == subprocess.check_output(
            args=[pex, "-c", "import colors; print(colors.blue('platform'))"]
        )
        .decode("utf-8")
        .strip()
    )


def test_platform_placeholder_seed(tmpdir):
    # type: (Tempdir) -> None

    result = run_pex_command(
        args=[
            "ansicolors==1.1.8",
            "-o",
            tmpdir.join("ansicolors-{platform}.pex"),
            "--seed",
            "verbose",
        ]
    )
    result.assert_success()

    seed_data = json.loads(result.output)
    pex = seed_data["seeded_from"]
    assert tmpdir.join("ansicolors-py2.py3-none-any.pex") == pex
    assert (
        colors.blue("platform")
        == subprocess.check_output(
            args=[pex, "-c", "import colors; print(colors.blue('platform'))"]
        )
        .decode("utf-8")
        .strip()
    )


@pytest.mark.skipif(
    IS_PYPY or sys.version_info[:2] < (3, 6), reason="The p537 distribution requires CPython >= 3.6"
)
def test_platform_placeholder_multiplatform(tmpdir):
    # type: (Tempdir) -> None

    result = run_pex_command(
        args=[
            "cowsay<6",
            "ansicolors==1.1.8",
            "p537==1.0.10",
            "--complete-platform",
            data.path("platforms", "linux-x86_64.json"),
            "--complete-platform",
            data.path("platforms", "macos-aarch64.json"),
            "-o",
            tmpdir.join("multiplatform-{platform}.pex"),
        ]
    )
    result.assert_success()

    pex = result.output.strip()
    assert (
        tmpdir.join("multiplatform-cp314-cp314-macosx_10_15_universal2.manylinux1_x86_64.pex")
        == pex
    )
    assert (
        colors.yellow("platform")
        == subprocess.check_output(
            args=[pex, "-c", "import colors; print(colors.yellow('platform'))"]
        )
        .decode("utf-8")
        .strip()
    )
