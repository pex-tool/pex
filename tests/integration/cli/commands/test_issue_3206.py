# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from testing.cli import run_pex3
from testing.lock import index_lock_artifacts
from testing.pytest_utils.tmp import Tempdir


def test_marker_conjunction_precedence(tmpdir):
    # type: (Tempdir) -> None

    lock_file = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--target-system",
        "linux",
        (
            "ansicolors==1.1.8; "
            'sys_platform == "linux" or sys_platform == "win32" and sys_platform == "aix"'
        ),
        "--indent",
        "2",
        "-o",
        lock_file,
    ).assert_success()

    lock_artifacts = index_lock_artifacts(lock_file)
    locked_artifact = lock_artifacts.pop(ProjectName("ansicolors"))
    assert not lock_artifacts, "Should have locked just 1 project."
    assert Version("1.1.8") == locked_artifact.pin.version
