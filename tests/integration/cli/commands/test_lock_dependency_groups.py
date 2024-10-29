# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from textwrap import dedent

from pex.common import safe_open
from pex.dist_metadata import Requirement
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.lockfile import json_codec
from pex.sorted_tuple import SortedTuple
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir

req = Requirement.parse


def test_lock_dependency_groups(tmpdir):
    # type: (Tempdir) -> None

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [dependency-groups]
                speak = ["cowsay==5.0"]
                """
            )
        )

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--group",
        "speak@{project}".format(project=project_dir),
        "ansicolors==1.1.8",
        "-o",
        lock,
        "--indent",
        "2",
    ).assert_success()

    lockfile = json_codec.load(lock)
    assert (
        SortedTuple((req("cowsay==5.0"), req("ansicolors==1.1.8")), key=str)
        == lockfile.requirements
    )
    assert 1 == len(lockfile.locked_resolves)
    locked_requirements = lockfile.locked_resolves[0].locked_requirements
    assert sorted(
        ((ProjectName("cowsay"), Version("5.0")), (ProjectName("ansicolors"), Version("1.1.8")))
    ) == sorted(
        (locked_req.pin.project_name, locked_req.pin.version) for locked_req in locked_requirements
    )
