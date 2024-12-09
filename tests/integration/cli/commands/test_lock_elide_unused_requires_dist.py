# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from typing import Dict

from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockedRequirement
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir


def index_locked_reqs(lockfile):
    # type: (Lockfile) -> Dict[ProjectName, LockedRequirement]
    return {
        locked_req.pin.project_name: locked_req
        for locked_resolve in lockfile.locked_resolves
        for locked_req in locked_resolve.locked_requirements
    }


def test_lock_elide_unused_requires_dist(tmpdir):
    # type: (Tempdir) -> None

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "requests==2.31.0",
        "--style",
        "universal",
        "--interpreter-constraint",
        ">=3.7,<3.14",
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()
    lockfile = json_codec.load(lock)

    elided_lock = tmpdir.join("elided_lock.json")
    run_pex3(
        "lock",
        "create",
        "requests==2.31.0",
        "--style",
        "universal",
        "--interpreter-constraint",
        ">=3.7,<3.14",
        "--elide-unused-requires-dist",
        "--indent",
        "2",
        "-o",
        elided_lock,
    ).assert_success()
    elided_lockfile = json_codec.load(elided_lock)

    assert lockfile != elided_lockfile

    locked_reqs = index_locked_reqs(lockfile)
    requests = locked_reqs[ProjectName("requests")]

    elided_locked_reqs = index_locked_reqs(elided_lockfile)
    elided_requests = elided_locked_reqs[ProjectName("requests")]

    assert requests != elided_requests

    assert requests.pin == elided_requests.pin
    assert list(requests.iter_artifacts()) == list(elided_requests.iter_artifacts())
    assert requests.requires_python == elided_requests.requires_python

    assert requests.requires_dists != elided_requests.requires_dists
    assert len(elided_requests.requires_dists) < len(requests.requires_dists)
    elided_deps = set(requests.requires_dists) - set(elided_requests.requires_dists)
    assert len(elided_deps) > 0
    assert not any(
        elided_dep.project_name in elided_locked_reqs for elided_dep in elided_deps
    ), "No dependencies that require extra activation should have been locked."

    run_pex3(
        "lock",
        "sync",
        "--style",
        "universal",
        "--interpreter-constraint",
        ">=3.7,<3.14",
        "--elide-unused-requires-dist",
        "--indent",
        "2",
        "--lock",
        lock,
    ).assert_success()
    assert elided_lockfile == json_codec.load(lock)
