# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.pep_440 import Version
from pex.resolve.lockfile import json_codec
from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


def test_uploaded_prior_to_filters_to_older_version(tmpdir):
    # type: (Any) -> None

    lock_file = os.path.join(str(tmpdir), "cowsay.lock.json")
    run_pex3(
        "lock",
        "create",
        "cowsay",
        "--pip-version",
        "26.0",
        "--uploaded-prior-to",
        "2023-09-20",
        "-o",
        lock_file,
    ).assert_success()

    lock = json_codec.load(lock_file)
    assert 1 == len(lock.locked_resolves)
    locked_resolve = lock.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)
    assert Version("6.0") == locked_resolve.locked_requirements[0].pin.version


def test_uploaded_prior_to_far_future_allows_latest(tmpdir):
    # type: (Any) -> None

    lock_file = os.path.join(str(tmpdir), "cowsay.lock.json")
    run_pex3(
        "lock",
        "create",
        "cowsay==6.1",
        "--pip-version",
        "26.0",
        "--uploaded-prior-to",
        "2063-04-05",
        "-o",
        lock_file,
    ).assert_success()

    lock = json_codec.load(lock_file)
    assert 1 == len(lock.locked_resolves)
    locked_resolve = lock.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)
    assert Version("6.1") == locked_resolve.locked_requirements[0].pin.version
