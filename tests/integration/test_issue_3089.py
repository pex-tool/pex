# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

from pex.artifact_url import VCS, ArtifactURL
from pex.dist_metadata import Requirement
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import VCSArtifact
from pex.resolve.lockfile import json_codec
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir


def test_url_requirement_constraints(tmpdir):
    # type: (Tempdir) -> None

    lock_file = tmpdir.join("lock.json")

    with open(tmpdir.join("constraint.txt"), "w") as fp:
        print("cowsay @ git+https://github.com/VaasuDevanS/cowsay-python@v5.0", file=fp)

    run_pex3(
        "lock", "create", "--constraints", fp.name, "cowsay", "--indent", "2", "-o", lock_file
    ).assert_success()

    lock = json_codec.load(lock_file)
    assert [Requirement.parse("cowsay")] == list(lock.requirements)
    assert len(lock.locked_resolves) == 1

    locked_resolve = lock.locked_resolves[0]
    locked_requirements_by_name = {
        locked_requirement.pin.project_name: locked_requirement
        for locked_requirement in locked_resolve.locked_requirements
    }
    locked_requirement = locked_requirements_by_name.pop(ProjectName("cowsay"))
    assert not locked_requirements_by_name

    assert Version("5") == locked_requirement.pin.version
    assert isinstance(locked_requirement.artifact, VCSArtifact)
    assert locked_requirement.artifact.vcs is VCS.Git
    assert "v5.0" == locked_requirement.artifact.requested_revision
    assert (
        ArtifactURL.parse("git+https://github.com/VaasuDevanS/cowsay-python@v5.0")
        == locked_requirement.artifact.url
    )
