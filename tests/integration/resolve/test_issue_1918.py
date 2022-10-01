# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os.path
import subprocess

import pytest

from pex.cli.testing import run_pex3
from pex.compatibility import commonpath
from pex.dist_metadata import Requirement
from pex.pip.version import PipVersion, PipVersionValue
from pex.requirements import VCS
from pex.resolve.locked_resolve import VCSArtifact
from pex.resolve.lockfile import json_codec
from pex.resolve.resolver_configuration import ResolverVersion
from pex.sorted_tuple import SortedTuple
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


VCS_URL = (
    "git+ssh://git@github.com/jonathaneunice/colors.git@c965f5b9103c5bd32a1572adb8024ebe83278fb0"
)


def has_ssh_access():
    # type: () -> bool
    process = subprocess.Popen(
        args=[
            "ssh",
            "-T",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "git@github.com",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output, _ = process.communicate()
    return "You've successfully authenticated" in output.decode()


@pytest.mark.skipif(
    not has_ssh_access(), reason="Password-less ssh to git@github.com is required for this test."
)
@pytest.mark.parametrize(
    ["requirement", "expected_url"],
    [
        pytest.param(
            "ansicolors @ {vcs_url}".format(vcs_url=VCS_URL), VCS_URL, id="direct-reference"
        ),
        pytest.param(
            *itertools.repeat("{vcs_url}#egg=ansicolors".format(vcs_url=VCS_URL), 2),
            id="pip-proprietary"
        ),
    ],
)
@pytest.mark.parametrize(
    "pip_version",
    [pytest.param(pip_version, id=pip_version.value) for pip_version in PipVersion.values()],
)
@pytest.mark.parametrize(
    "resolver_version",
    [
        pytest.param(resolver_version, id=resolver_version.value)
        for resolver_version in ResolverVersion.values()
    ],
)
def test_redacted_requirement_handling(
    tmpdir,  # type: Any
    requirement,  # type: str
    expected_url,  # type: str
    pip_version,  # type: PipVersionValue
    resolver_version,  # type: ResolverVersion.Value
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "--pip-version",
        str(pip_version),
        "--resolver-version",
        str(resolver_version),
        requirement,
        "-o",
        lock,
        "--indent",
        "2",
    ).assert_success()
    lockfile = json_codec.load(lock)
    assert SortedTuple([Requirement.parse("ansicolors")]) == lockfile.requirements

    assert 1 == len(lockfile.locked_resolves)
    locked_resolve = lockfile.locked_resolves[0]

    assert 1 == len(locked_resolve.locked_requirements)
    locked_requirement = locked_resolve.locked_requirements[0]

    artifacts = list(locked_requirement.iter_artifacts())
    assert 1 == len(artifacts)
    artifact = artifacts[0]

    assert isinstance(artifact, VCSArtifact)
    assert VCS.Git is artifact.vcs
    assert expected_url == artifact.url

    pex_root = os.path.join(str(tmpdir), "pex_root")
    result = run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            lock,
            "--",
            "-c",
            "import colors; print(colors.__file__)",
        ]
    )
    result.assert_success()
    assert pex_root == commonpath([pex_root, result.output.strip()])
