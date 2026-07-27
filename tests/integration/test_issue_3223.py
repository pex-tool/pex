# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from uuid import uuid4

import pytest

from pex.cache import access
from pex.cache.dirs import VenvDirs
from pex.common import safe_open
from pex.os import WINDOWS
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir
from testing.scie import has_provider

if TYPE_CHECKING:
    from typing import Dict, List


@pytest.mark.parametrize(
    "extra_args",
    [
        pytest.param([], id="PEX"),
        pytest.param(["--sh-boot"], id="SH_BOOT"),
        pytest.param(["--scie", "eager", "--scie-only"], id="SCIE"),
    ],
)
def test_venv_direct_execution_prune_time(
    tmpdir,  # type: Tempdir
    extra_args,  # type: List[str]
):
    # type: (...) -> None

    if WINDOWS and "--sh-boot" in extra_args:
        pytest.skip("The direct execution of --sh-boot shebang PEXes does not work on Windows.")
    if "--scie" in extra_args and not has_provider():
        pytest.skip(
            "Either A PBS or PyPy release must be available for the current interpreter to run "
            "this test."
        )

    resources = tmpdir.join("resources")
    with safe_open(os.path.join(resources, "generate-unique-pex-hash"), "w") as fp:
        fp.write(uuid4().hex)

    pex = tmpdir.join("pex")
    run_pex_command(
        args=["-D", resources, "cowsay==5.0", "-c", "cowsay", "-o", pex, "--venv", "prepend"]
        + extra_args
    ).assert_success()
    pex_hash = PexInfo.from_pex(pex).pex_hash

    def collect_venv_access_times():
        # type: () -> Dict[VenvDirs, float]
        return {
            directory: access_time
            for directory, access_time in access.iter_all_cached_pex_dirs()
            if isinstance(directory, VenvDirs) and directory.pex_hash == pex_hash
        }

    assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"])
    access_times = collect_venv_access_times()

    assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"])
    new_access_times = collect_venv_access_times()

    for venv_dirs, access_time in access_times.items():
        new_access_time = new_access_times.pop(venv_dirs)
        assert (
            new_access_time > access_time
        ), "Expected direct execution to bump the access time for {venv_dir}".format(
            venv_dir=venv_dirs.path
        )
    assert not new_access_times
