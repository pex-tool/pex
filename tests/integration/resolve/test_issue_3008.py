# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.resolve.lockfile import json_codec
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


def test_multiple_unnamed_repos_works_issue_3008_op(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")
    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "-o",
        lock,
        "--style",
        "universal",
        "--pip-version",
        "latest-compatible",
        "--target-system",
        "linux",
        "--target-system",
        "mac",
        "--indent",
        "2",
        "--find-links",
        "https://wheels.pantsbuild.org/simple",
        "--no-pypi",
        "--index",
        "https://pypi.org/simple/",
        "--index",
        "pytorch_cpu=https://download.pytorch.org/whl/cpu",
        "--source",
        "pytorch_cpu=torch; sys_platform != 'darwin'",
        "--interpreter-constraint",
        "CPython<3.12,>=3.11",
        "torch==2.5.1; sys_platform == 'darwin'",
        "torch==2.5.1+cpu; sys_platform != 'darwin'",
    ).assert_success()

    assert 2 == len(json_codec.load(lock).locked_resolves), "Expected a split resolve."
