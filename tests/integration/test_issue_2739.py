# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import FileArtifact
from pex.resolve.lockfile import json_codec
from pex.resolve.resolved_requirement import Pin
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


def test_tar_bz2(tmpdir):
    # type: (Any) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "python-constraint==1.4.0",
        "-o",
        lock,
        "--indent",
        "2",
    ).assert_success()

    lock_file = json_codec.load(lock)
    assert len(lock_file.locked_resolves) == 1

    locked_resolve = lock_file.locked_resolves[0]
    assert len(locked_resolve.locked_requirements) == 1

    locked_requirement = locked_resolve.locked_requirements[0]
    assert Pin(ProjectName("python-constraint"), Version("1.4.0")) == locked_requirement.pin
    assert isinstance(locked_requirement.artifact, FileArtifact)
    assert locked_requirement.artifact.is_source
    assert locked_requirement.artifact.filename.endswith(".tar.bz2")
    assert not locked_requirement.additional_artifacts

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=["--pex-root", pex_root, "--runtime-pex-root", pex_root, "--lock", lock, "-o", pex]
    ).assert_success()

    assert (
        b"1.4.0"
        == subprocess.check_output(
            args=[pex, "-c", "from constraint.version import __version__; print(__version__)"]
        ).strip()
    )
