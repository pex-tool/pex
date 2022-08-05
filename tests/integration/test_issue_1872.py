# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
import subprocess
import sys

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


def execute(
    *args,  # type: str
    **env  # type: Any
):
    # type: (...) -> str
    env = make_env(**env)
    process = subprocess.Popen(args=args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    message = (
        "Executed `{args}` exit code {exit_code}:\n"
        "Environment:\n"
        "{env}\n"
        "\n"
        "STDOUT:\n"
        "===\n"
        "{stdout}\n"
        "\n"
        "STDERR:\n"
        "===\n"
        "{stderr}\n".format(
            args=" ".join(args),
            env="\n".join("{key}={value}".format(key=k, value=v) for k, v in env.items()),
            exit_code=process.returncode,
            stdout=stdout.decode("utf-8"),
            stderr=stderr.decode("utf-8"),
        )
    )
    assert 0 == process.returncode, message
    return message


def test_pep_518_venv_pex_env_scrubbing(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    pex_pex = os.path.join(str(tmpdir), "pex")
    execute("tox", "-e", "package", "--", "--local", "--pex-output-file", pex_pex)

    lock = os.path.join(str(tmpdir), "lock.json")
    message = execute(
        # Although the package script requires Python 3 to create the Pex PEX, we should be able to
        # execute the Pex PEX with any interpreter.
        sys.executable,
        pex_pex,
        "lock",
        "create",
        pex_project_dir,
        "-o",
        lock,
        "--indent",
        "2",
        PEX_SCRIPT="pex3",
    )
    print(">>> {}".format(message), file=sys.stderr)
    print(">>> Exists {}?: {}".format(pex_pex, os.path.exists(pex_pex)))

    lockfile = json_codec.load(lock)
    assert 1 == len(lockfile.locked_resolves)

    locked_resolve = lockfile.locked_resolves[0]
    assert 1 == len(locked_resolve.locked_requirements)

    locked_requirement = locked_resolve.locked_requirements[0]
    assert Pin(ProjectName("pex"), Version(__version__)) == locked_requirement.pin
    assert isinstance(locked_requirement.artifact, LocalProjectArtifact)
    assert pex_project_dir == locked_requirement.artifact.directory
    assert not locked_requirement.additional_artifacts
