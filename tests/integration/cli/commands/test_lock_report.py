# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
import os.path
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.pip.version import PipVersion
from pex.resolve.resolver_configuration import ResolverVersion
from testing import IS_PYPY
from testing.cli import run_pex3
from testing.pytest_utils import IS_CI
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    IS_CI and IS_PYPY,
    reason=(
        "The PyPy CI tests are slow generally; this test is slow in particular (due to a large "
        "parameter matrix), and we gain no new information from the PyPy tests over the CPython "
        "tests in this case."
    ),
)
@pytest.mark.parametrize(
    ["pip_version", "resolver_version"],
    [
        pytest.param(
            pip_version,
            resolver_version,
            id="{pip_version}-{resolver_version}".format(
                pip_version=pip_version, resolver_version=resolver_version
            ),
        )
        for pip_version in PipVersion.values()
        # N.B.: We skip vendored Pip since it does not support "--avoid-downloads" (i.e.:
        # `pip install --dry-run --ignore-installed --report`); so no comparison between report and
        # download mode can be done.
        if not pip_version is PipVersion.VENDORED and pip_version.requires_python_applies()
        for resolver_version in ResolverVersion.values()
        if ResolverVersion.applies(resolver_version, pip_version)
    ],
)
def test_download_lock_and_report_lock_identical(
    tmpdir,  # type: Tempdir
    pip_version,  # type: PipVersion
    resolver_version,  # type: ResolverVersion
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = example
                version = 0.0.1
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write("from setuptools import setup; setup()")

    requirements = tmpdir.join("requirements.txt")
    with open(requirements, "w") as fp:
        fp.write(
            dedent(
                """\
                # Stress local projects.
                {project_dir}

                # Stress extras handling, sdists and wheels.
                requests[socks]

                # Stress VCS handling including subdirectories.
                git+https://github.com/SerialDev/sdev_py_utils@bd4d36a0#egg=sdev_logging_utils&subdirectory=sdev_logging_utils

                # Stress archive handling.
                cowsay @ https://github.com/VaasuDevanS/cowsay-python/archive/dcf7236f0b5ece9ed56e91271486e560526049cf.zip
                """.format(
                    project_dir=project_dir
                )
            )
        )

    pex_root = tmpdir.join("pex-root")
    lock_report = tmpdir.join("lock_report.json")
    run_pex3(
        "lock",
        "create",
        "--avoid-downloads",
        "--pex-root",
        pex_root,
        "--pip-version",
        str(pip_version),
        "--resolver-version",
        str(resolver_version),
        "--style",
        "sources",
        "-r",
        requirements,
        "--indent",
        "2",
        "-o",
        lock_report,
        "-v",
        "--pip-log",
        tmpdir.join("pip-report.log"),
    ).assert_success()

    lock_download = tmpdir.join("lock_download.json")
    run_pex3(
        "lock",
        "create",
        "--no-avoid-downloads",
        "--pex-root",
        pex_root,
        "--pip-version",
        str(pip_version),
        "--resolver-version",
        str(resolver_version),
        "--style",
        "sources",
        "-r",
        requirements,
        "--indent",
        "2",
        "-o",
        lock_download,
        "-v",
        "--pip-log",
        tmpdir.join("pip-download.log"),
    ).assert_success()

    assert filecmp.cmp(lock_report, lock_download, shallow=False)
