# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess
import tarfile
from textwrap import dedent

import pytest

from pex.common import is_exe, safe_open
from pex.compatibility import urlparse
from pex.fetcher import URLFetcher
from pex.pep_440 import Version
from pex.pip.version import PipVersion
from pex.typing import TYPE_CHECKING
from testing import IS_LINUX, run_pex_command

if TYPE_CHECKING:
    from typing import Any


# TODO(John Sirois): Include a test of >= Pip 24.2 when Pex adds support for it.
#  See: https://github.com/pex-tool/pex/issues/2471
@pytest.mark.skipif(
    PipVersion.DEFAULT > PipVersion.VENDORED and PipVersion.DEFAULT.version < Version("24.2"),
    reason=(
        "Although Pex's vendored Pip is patched to handle statically linked musl libc CPython, no "
        "version of Pip Pex supports handles these Pythons until Pip 24.2"
    ),
)
@pytest.mark.skipif(
    not IS_LINUX,
    reason="This test tests statically linked musl libc CPython which is only available for Linux.",
)
def test_statically_linked_musl_libc_cpython_support(tmpdir):
    # type: (Any) -> None

    pbs_distribution_url = (
        "https://github.com/indygreg/python-build-standalone/releases/download/20221220/"
        "cpython-3.10.9+20221220-x86_64_v3-unknown-linux-musl-install_only.tar.gz"
    )
    pbs_distribution = os.path.join(
        str(tmpdir),
        os.path.basename(urlparse.urlparse(pbs_distribution_url).path),
    )
    with URLFetcher().get_body_stream(pbs_distribution_url) as read_fp, open(
        pbs_distribution, "wb"
    ) as write_fp:
        shutil.copyfileobj(read_fp, write_fp)
    with tarfile.open(pbs_distribution) as tf:
        tf.extractall(str(tmpdir))
    statically_linked_musl_libc_cpython = os.path.join(str(tmpdir), "python", "bin", "python3")
    assert is_exe(statically_linked_musl_libc_cpython)

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["fortune==1.1.1", "-c", "fortune", "-o", pex],
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
