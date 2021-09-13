# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import shutil
import subprocess
import sys

from pex.pex_info import PexInfo
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING
from pex.variables import unzip_dir

if TYPE_CHECKING:
    from typing import Any


def test_layout_identification(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex_file = os.path.join(str(tmpdir), "a.pex")
    run_pex_command(
        args=["-o", pex_file, "--pex-root", pex_root, "--runtime-pex-root", pex_root]
    ).assert_success()

    pex_hash = PexInfo.from_pex(pex_file).pex_hash
    assert pex_hash is not None

    expected_unzip_dir = unzip_dir(pex_root, pex_hash)
    assert not os.path.exists(expected_unzip_dir)

    subprocess.check_call(args=[pex_file, "-c", ""])
    assert os.path.isdir(expected_unzip_dir)

    shutil.rmtree(expected_unzip_dir)
    os.chmod(pex_file, 0o644)
    subprocess.check_call(args=[sys.executable, pex_file, "-c", ""])
    assert os.path.isdir(expected_unzip_dir)
