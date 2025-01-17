# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess
import tarfile
from textwrap import dedent

import pytest

from pex.atomic_directory import atomic_directory
from pex.common import safe_open
from pex.compatibility import urlparse
from pex.executables import is_exe
from pex.fetcher import URLFetcher
from pex.pip.version import PipVersion, PipVersionValue
from pex.typing import TYPE_CHECKING
from testing import IS_LINUX, run_pex_command

if TYPE_CHECKING:
    from typing import Any, Iterator


def musl_libc_capable_pip_versions():
    # type: () -> Iterator[PipVersionValue]

    for version in PipVersion.values():
        if not version.requires_python_applies():
            continue
        if version is PipVersion.VENDORED or version >= PipVersion.v24_2:
            yield version


MUSL_LIBC_CAPABLE_PIP_VERSIONS = tuple(musl_libc_capable_pip_versions())


@pytest.fixture
def statically_linked_musl_libc_cpython(shared_integration_test_tmpdir):
    # type: (str) -> str
    pbs_distribution_url = (
        "https://github.com/astral-sh/python-build-standalone/releases/download/20221220/"
        "cpython-3.10.9+20221220-x86_64_v3-unknown-linux-musl-install_only.tar.gz"
    )
    tarball_name = os.path.basename(urlparse.urlparse(pbs_distribution_url).path)
    pbs_distribution = os.path.join(shared_integration_test_tmpdir, "PBS-dists", tarball_name)
    with atomic_directory(pbs_distribution) as chroot:
        if not chroot.is_finalized():
            tarball_dest = os.path.join(chroot.work_dir, tarball_name)
            with URLFetcher().get_body_stream(pbs_distribution_url) as read_fp, open(
                tarball_dest, "wb"
            ) as write_fp:
                shutil.copyfileobj(read_fp, write_fp)
            with tarfile.open(tarball_dest) as tf:
                tf.extractall(chroot.work_dir)
            statically_linked_musl_libc_cpython = os.path.join(
                chroot.work_dir, "python", "bin", "python3"
            )
            assert is_exe(statically_linked_musl_libc_cpython)

    return os.path.join(pbs_distribution, "python", "bin", "python3")


@pytest.mark.skipif(
    not MUSL_LIBC_CAPABLE_PIP_VERSIONS,
    reason=(
        "Although Pex's vendored Pip is patched to handle statically linked musl libc CPython, no "
        "version of Pip Pex supports handles these Pythons until Pip 24.2 and none of these "
        "versions are supported by the current interpreter."
    ),
)
@pytest.mark.skipif(
    not IS_LINUX,
    reason="This test tests statically linked musl libc CPython which is only available for Linux.",
)
@pytest.mark.parametrize(
    "pip_version",
    [pytest.param(version, id=str(version)) for version in MUSL_LIBC_CAPABLE_PIP_VERSIONS],
)
def test_statically_linked_musl_libc_cpython_support(
    tmpdir,  # type: Any
    pip_version,  # type: PipVersionValue
    statically_linked_musl_libc_cpython,  # type: str
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["fortune==1.1.1", "-c", "fortune", "--pip-version", str(pip_version), "-o", pex],
        python=statically_linked_musl_libc_cpython,
    ).assert_success()

    fortune_db = os.path.join(str(tmpdir), "fortunes")
    with safe_open(fortune_db, "w") as fp:
        fp.write(
            dedent(
                """\
                A day for firm decisions!!!!!  Or is it?
                %
                """
            )
        )
    output = subprocess.check_output(args=[pex, fortune_db])
    assert b"A day for firm decisions!!!!!  Or is it?\n" == output, output.decode("utf-8")
