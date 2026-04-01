# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import sys

import pytest

from pex.pep_440 import Version
from pex.resolve.lockfile import json_codec
from pex.resolve.package_repository import PYPI
from pex.typing import TYPE_CHECKING
from testing import make_env
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    sys.version_info < (3, 9),
    reason="Pip 26.0 requires Python >= 3.9 for --uploaded-prior-to support.",
)
def test_compatible_version_fallback_compatibility(tmpdir):
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
        # Bypass devpi in integration tests until upload-time is supported
        # https://github.com/devpi/devpi/issues/1061
        env=make_env(PIP_INDEX_URL=PYPI),
    ).assert_success()

    lock = json_codec.load(lock_file)
    assert 1 == len(lock.locked_resolves)
    locked_resolve = lock.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)
    assert Version("6.0") == locked_resolve.locked_requirements[0].pin.version


@pytest.mark.skipif(
    sys.version_info < (3, 9),
    reason="Pip 26.0 requires Python >= 3.9 for --uploaded-prior-to support.",
)
def test_uploaded_prior_to_latest_compatible_pip(tmpdir):
    # type: (Any) -> None

    lock_file = os.path.join(str(tmpdir), "cowsay.lock.json")
    run_pex3(
        "lock",
        "create",
        "cowsay==6.1",
        "--pip-version",
        "latest-compatible",
        "--uploaded-prior-to",
        "2063-04-05",
        "-o",
        lock_file,
        env=make_env(PIP_INDEX_URL=PYPI),
    ).assert_success()


@pytest.mark.skipif(sys.version_info > (3, 8), reason="fallback specific behavior")
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
        env=make_env(PIP_INDEX_URL=PYPI),
    ).assert_success(
        # If pex.pip.installation.compatible_version downgraded the pip
        # version, --uploaded-prior-to is dropped as well to make sure we can
        # proceed without a new crash
        expected_error_re=r".*PEXWarning: .*Using Pip .* instead",
        re_flags=re.DOTALL,
    )

    lock = json_codec.load(lock_file)
    assert 1 == len(lock.locked_resolves)
    locked_resolve = lock.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)
    assert locked_resolve.locked_requirements[0].pin.version >= Version("6.1")
