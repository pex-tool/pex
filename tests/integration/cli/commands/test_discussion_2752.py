# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys
from typing import Optional

import pytest

from pex import targets
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.typing import TYPE_CHECKING
from testing import PY310, ensure_python_interpreter
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    import attr  # vendor:skip
else:
    from pex.third_party import attr


@pytest.mark.skipif(
    (
        not PipVersion.v25_0.requires_python_applies(targets.current())
        or not PipVersion.v25_1.requires_python_applies(targets.current())
    ),
    reason="This test needs to test the transition from Pip 25.0 to Pip >= 25.1.",
)
def test_multiplatform_abi3_wheel_lock(tmpdir):
    # type: (Tempdir) -> None

    # Previously, for Pip >= 25.1, abi3 wheels with multiple (dot-separated) platforms would fail
    # to be included in locks. We compare older Pip with newer Pip here to ensure no such change.

    def create_lock(
        pip_version,  # type: PipVersionValue
        python=None,  # type: Optional[str]
    ):
        # type: (...) -> Lockfile
        result = run_pex3(
            "lock",
            "create",
            "dbt-extractor==0.6.0",
            "--style",
            "universal",
            "--target-system",
            "linux",
            "--target-system",
            "mac",
            "--interpreter-constraint",
            "~=3.12",
            "--resolver-version",
            "pip-2020-resolver",
            "--pip-version",
            str(pip_version),
            python=python,
        )
        result.assert_success()
        return attr.evolve(json_codec.loads(result.output), pip_version=PipVersion.VENDORED)

    lock_pip_vendored = create_lock(
        PipVersion.VENDORED,
        python=(
            sys.executable
            if PipVersion.VENDORED.requires_python_applies(targets.current())
            else ensure_python_interpreter(PY310)
        ),
    )

    lock_pip_25_0 = create_lock(PipVersion.v25_0)
    assert lock_pip_vendored == lock_pip_25_0

    lock_pip_25_1_or_newer = create_lock(PipVersion.LATEST_COMPATIBLE)
    assert lock_pip_vendored == lock_pip_25_1_or_newer
