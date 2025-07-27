# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import shutil

from pex.dist_metadata import ProjectNameAndVersion
from pex.interpreter import PythonInterpreter
from pex.pex_info import PexInfo
from testing import IS_ARM_64, IS_MAC, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


def test_find_links_url_escaping(
    tmpdir,  # type: Tempdir
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    # N.B.: The use of --intransitive here (and --no-compress and --no-pre-install-wheels below)
    # just serve to make this issue reproduction less expensive: torch and its dependency set are
    # several GB worth.
    lock = tmpdir.join("lock.json")
    pex_root = tmpdir.join("pex_root")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--python-path",
        py310.binary,
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

    pex = tmpdir.join("pex")
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
        python=py310.binary,
    ).assert_success()

    pex_info = PexInfo.from_pex(pex)
    assert len(pex_info.distributions) == 1
    wheel, _ = pex_info.distributions.popitem()
    assert ProjectNameAndVersion("torch", "2.0.1+cpu") == ProjectNameAndVersion.from_filename(wheel)
