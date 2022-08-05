# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LocalProjectArtifact
from pex.resolve.lockfile import json_codec
from pex.resolve.resolved_requirement import Pin
from pex.testing import make_env
from pex.typing import TYPE_CHECKING
from pex.version import __version__

if TYPE_CHECKING:
    from typing import Any


def test_pep_518_venv_pex_env_scrubbing(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    pex_pex = os.path.join(str(tmpdir), "pex")
    subprocess.check_call(
        args=["tox", "-e", "package", "--", "--local", "--pex-output-file", pex_pex]
    )

    lock = os.path.join(str(tmpdir), "lock.json")
    subprocess.check_call(
        args=[pex_pex, "lock", "create", pex_project_dir, "-o", lock, "--indent", "2"],
        env=make_env(PEX_SCRIPT="pex3"),
    )
    lockfile = json_codec.load(lock)
    assert 1 == len(lockfile.locked_resolves)

    locked_resolve = lockfile.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)

    locked_requirement = locked_resolve.locked_requirements[0]
    assert Pin(ProjectName("pex"), Version(__version__)) == locked_requirement.pin
    assert isinstance(locked_requirement.artifact, LocalProjectArtifact)
    assert pex_project_dir == locked_requirement.artifact.directory
    assert not locked_requirement.additional_artifacts