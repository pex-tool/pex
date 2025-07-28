# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re
import sys

import pytest

from pex.version import __version__
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

skip_if_locked_dev_cmd_not_compatible = pytest.mark.skipif(
    sys.version_info[:2] < (3, 9),
    reason=(
        "The dev-cmd project started shipping embedded locks when it moved to supporting "
        "Python>=3.9."
    ),
)


@pytest.fixture(scope="session")
def dev_cmd_version():
    # type: () -> str

    result = run_pex_command(args=["dev-cmd", "-c", "dev-cmd", "--", "-V"])
    result.assert_success()
    return str(result.output)


@skip_if_locked_dev_cmd_not_compatible
def test_nominal(dev_cmd_version):
    # type: (str) -> None

    run_pex3("run", "dev-cmd", "-V").assert_success(expected_output_re=re.escape(dev_cmd_version))


@skip_if_locked_dev_cmd_not_compatible
def test_locked_wheel(dev_cmd_version):
    # type: (str) -> None

    run_pex3(
        "run", "--only-wheel", "dev-cmd", "--locked", "require", "dev-cmd", "-V"
    ).assert_success(expected_output_re=re.escape(dev_cmd_version))


@skip_if_locked_dev_cmd_not_compatible
def test_locked_sdist(dev_cmd_version):
    # type: (str) -> None

    run_pex3(
        "run", "--only-build", "dev-cmd", "--locked", "require", "dev-cmd", "-V"
    ).assert_success(expected_output_re=re.escape(dev_cmd_version))


@skip_if_locked_dev_cmd_not_compatible
def test_locked_require_error(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--from",
        pex_project_dir,
        "pex",
        "-V",
    ).assert_success(expected_output_re=re.escape(__version__))

    # N.B.: Although we now require a lock, the tool venv is cached; so we should get no error.
    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--locked",
        "require",
        "--from",
        pex_project_dir,
        "pex",
        "-V",
    ).assert_success(expected_output_re=re.escape(__version__))

    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--refresh",
        "--locked",
        "require",
        "--from",
        pex_project_dir,
        "pex",
        "-V",
    ).assert_failure(
        expected_error_re=r".*^A tool lock file was required but none was found\.$.*",
        re_flags=re.MULTILINE | re.DOTALL,
    )


@skip_if_locked_dev_cmd_not_compatible
def test_locked_require_backoff(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--locked",
        "require",
        "--from",
        pex_project_dir,
        "pex",
        "-V",
    ).assert_failure(
        expected_error_re=r".*^A tool lock file was required but none was found\.$.*",
        re_flags=re.MULTILINE | re.DOTALL,
    )

    # We should go back to success in auto mode.
    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--from",
        pex_project_dir,
        "pex",
        "-V",
    ).assert_success(expected_output_re=re.escape(__version__))


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 9), reason="The black 25.1 release requires Python>=3.9."
)
def test_entry_point_with_extras():
    # type: () -> None

    run_pex3("run", "--from", "black[d]==25.1", "blackd", "--version").assert_success(
        expected_output_re=re.escape("blackd, version 25.1.0")
    )
