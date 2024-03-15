# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os.path
import shutil

from pex.dist_metadata import ProjectNameAndVersion
from pex.pex_info import PexInfo
from pex.typing import TYPE_CHECKING
from testing import IS_ARM_64, IS_MAC, PY310, ensure_python_interpreter, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


def test_find_links_url_escaping(tmpdir):
    # type: (Any) -> None

    # N.B.: The use of --intransitive here (and --no-compress and --no-pre-install-wheels below)
    # just serve to make this issue reproduction less expensive: torch and its dependency set are
    # several GB worth.
    lock = os.path.join(str(tmpdir), "lock.json")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--interpreter-constraint",
        "CPython==3.10.*",
        "--style",
        "universal",
        "--resolver-version",
        "pip-2020-resolver",
        "--find-links",
        "https://download.pytorch.org/whl/torch_stable.html",
        "torch==2.0.1+cpu",
        "--intransitive",
        "--target-system",
        "linux",
        "--target-system",
        "mac",
        "-o",
        lock,
        "--indent",
        "2",
    ).assert_success()

    # The torch 2.0.1+cpu wheel is only published for x86_64 for Linux and Windows.
    if IS_MAC or IS_ARM_64:
        return

    # Force the torch 2.0.1+cpu wheel to be re-downloaded from the lock.
    shutil.rmtree(pex_root)

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--lock",
            lock,
            "--intransitive",
            "--no-compress",
            "--no-pre-install-wheels",
            "-o",
            pex,
        ],
        python=ensure_python_interpreter(PY310),
    ).assert_success()

    pex_info = PexInfo.from_pex(pex)
    assert len(pex_info.distributions) == 1
    wheel, _ = pex_info.distributions.popitem()
    assert ProjectNameAndVersion("torch", "2.0.1+cpu") == ProjectNameAndVersion.from_filename(wheel)
