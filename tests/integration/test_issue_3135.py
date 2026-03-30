# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess

import pytest

from pex.compatibility import commonpath
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import IS_PYPY, PY_VER, run_pex_command
from testing.pytest_utils.tmp import Tempdir

skip_if_openturns_1_22_not_compatible = pytest.mark.skipif(
    IS_PYPY or PY_VER < (3, 8) or PY_VER >= (3, 13),
    reason="The openturns 1.22 wheels under test are only publich for CPython>=3.8,<3.13.",
)


def assert_openturns_pex(
    tmpdir,  # type: Tempdir
    *extra_pex_args  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "openturns==1.22",
            "-o",
            pex,
        ]
    ).assert_success()

    assert pex_root == commonpath(
        (
            pex_root,
            subprocess.check_output(args=[pex, "-c", "import openturns; print(openturns.__file__)"])
            .decode("utf-8")
            .strip(),
        )
    )


@skip_if_openturns_1_22_not_compatible
def test_wheel_file_name_tags_trump_bad_tag_metadata(tmpdir):
    # type: (Tempdir) -> None

    assert_openturns_pex(tmpdir)


@skip_if_openturns_1_22_not_compatible
def test_platform_tags_trump_missing_tag_metadata(tmpdir):
    # type: (Tempdir) -> None

    venv = Virtualenv.create(
        tmpdir.join("venv"), install_pip=InstallationChoice.YES, other_installs=["openturns==1.22"]
    )
    assert_openturns_pex(tmpdir, "--venv-repository", venv.venv_dir)
