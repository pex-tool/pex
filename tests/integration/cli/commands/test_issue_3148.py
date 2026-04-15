# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp

from testing import PY311, ensure_python_interpreter, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


def lock_nautobot(lock_file, *extra_lock_args):
    args = [
        "lock",
        "create",
        "nautobot @ git+https://github.com/utsc-networking/nautobot@utsc-custom",
        "--intransitive",
        "--pip-version",
        "latest-compatible",
        "--indent",
        "2",
        "-o",
        lock_file,
    ]
    run_pex3(*(args + list(extra_lock_args))).assert_success()


def test_issue_3148(tmpdir):
    # type: (Tempdir) -> None

    python311 = ensure_python_interpreter(PY311)

    lock_avoid_downloads = tmpdir.join("lock.avoid-downloads.json")
    lock_nautobot(lock_avoid_downloads, "--python", python311, "--avoid-downloads")
    pex_avoid_downloads = tmpdir.join("avoid-downloads.pex")
    run_pex_command(
        args=[
            "--python",
            python311,
            "--lock",
            lock_avoid_downloads,
            "--intransitive",
            "-o",
            pex_avoid_downloads,
        ],
        python=python311,
    ).assert_success()

    lock_no_avoid_downloads = tmpdir.join("lock.no-avoid-downloads.json")
    lock_nautobot(lock_no_avoid_downloads, "--python", python311, "--no-avoid-downloads")
    pex_no_avoid_downloads = tmpdir.join("no-avoid-downloads.pex")
    run_pex_command(
        args=[
            "--python",
            python311,
            "--lock",
            lock_no_avoid_downloads,
            "--intransitive",
            "-o",
            pex_no_avoid_downloads,
        ],
    ).assert_success()

    assert filecmp.cmp(lock_avoid_downloads, lock_no_avoid_downloads, shallow=False)
    assert filecmp.cmp(pex_avoid_downloads, pex_no_avoid_downloads, shallow=False)
