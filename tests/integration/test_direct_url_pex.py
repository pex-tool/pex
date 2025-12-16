# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import sys

import pytest

from pex.pex_info import PexInfo
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8), reason="The cowsay 6.1 wheel requires Python >= 3.8."
)
def test_direct_url_pex(tmpdir):
    # type: (Tempdir) -> None

    pex = tmpdir.join("pex")
    direct_url = (
        "https://files.pythonhosted.org/packages/f1/13/"
        "63c0a02c44024ee16f664e0b36eefeb22d54e93531630bd99e237986f534/cowsay-6.1-py3-none-any.whl"
    )
    run_pex_command(args=[direct_url, "-c", "cowsay", "-o", pex]).assert_success()
    assert b"| Moo! |" in subprocess.check_output(args=[pex, "-t", "Moo!"])
    assert ["cowsay @ {url}".format(url=direct_url)] == list(PexInfo.from_pex(pex).requirements)
