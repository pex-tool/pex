# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
from collections import deque
from typing import Dict, Tuple

import pytest

from pex.atomic_directory import atomic_directory
from pex.dist_metadata import Requirement
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import LockedRequirement
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.sorted_tuple import SortedTuple
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir


@pytest.fixture(scope="session")
def input_requirements(pex_project_dir):
    # type: (str) -> Tuple[str, ...]

    return "{pex}[management]".format(pex=pex_project_dir), "ansicolors", "requests"


@pytest.fixture(scope="session")
def lock(
    input_requirements,  # type: Tuple[str, ...]
    shared_integration_test_tmpdir,  # type: str
):
    # type: (...) -> str

    lock_dir = os.path.join(shared_integration_test_tmpdir, "test_lock_subset")
    with atomic_directory(lock_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            run_pex3(
                "lock",
                "create",
                # N.B.: This just makes the analysis in test_lock_subset_subset simpler.
                "--elide-unused-requires-dist",
                "--indent",
                "2",
                "-o",
                os.path.join(atomic_dir.work_dir, "lock.json"),
                *input_requirements
            ).assert_success()
    return os.path.join(lock_dir, "lock.json")


def test_lock_subset_full(
    tmpdir,  # type: Tempdir
    lock,  # type: str
    input_requirements,  # type: Tuple[str, ...]
):
    # type: (...) -> None

    subset_lock = tmpdir.join("subset.lock")
    run_pex3(
        "lock", "subset", "--lock", lock, "--indent", "2", "-o", subset_lock, *input_requirements
    ).assert_success()
    assert json_codec.load(subset_lock) == json_codec.load(lock)


def index(lock):
    # type: (str) -> Tuple[Lockfile, Dict[ProjectName, LockedRequirement]]

    lockfile = json_codec.load(lock)
    assert 1 == len(lockfile.locked_resolves)
    locked_resolve = lockfile.locked_resolves[0]
    return lockfile, {
        locked_req.pin.project_name: locked_req for locked_req in locked_resolve.locked_requirements
    }


def test_lock_subset_subset(
    tmpdir,  # type: Tempdir
    lock,  # type: str
):
    # type: (...) -> None

    subset_lock = tmpdir.join("subset.lock")
    run_pex3(
        "lock",
        "subset",
        "--lock",
        lock,
        "--indent",
        "2",
        "-o",
        subset_lock,
        "ansicolors",
        "requests",
    ).assert_success()

    original_lockfile, original_locked_reqs = index(lock)
    subset_lockfile, subset_locked_reqs = index(subset_lock)
    assert subset_lockfile != original_lockfile
    assert (
        SortedTuple((Requirement.parse("ansicolors"), Requirement.parse("requests")))
        == subset_lockfile.requirements
    )
    assert ProjectName("pex") not in subset_locked_reqs

    # Check top-level subset requirements are in there.
    for project_name in ProjectName("ansicolors"), ProjectName("requests"):
        assert original_locked_reqs[project_name] == subset_locked_reqs.pop(project_name)

    requests = original_locked_reqs[ProjectName("requests")]
    requests_deps = {}  # type: Dict[ProjectName, LockedRequirement]
    to_walk = deque(dist.project_name for dist in requests.requires_dists)
    while to_walk:
        dep = to_walk.popleft()
        if dep in requests_deps:
            continue
        requests_deps[dep] = subset_locked_reqs.pop(dep)
        to_walk.extend(d.project_name for d in requests_deps[dep].requires_dists)

    assert (
        not subset_locked_reqs
    ), "Expected subset to just contain ansicolors, requests, and requests' transitive deps"
    for project_name, locked_req in requests_deps.items():
        assert locked_req == original_locked_reqs[project_name]


def test_lock_subset_miss(lock):
    # type: (str) -> None

    _, original_locked_reqs = index(lock)
    requests_version = original_locked_reqs[ProjectName("requests")].pin.version
    run_pex3(
        "lock", "subset", "--lock", lock, "requests!={version}".format(version=requests_version)
    ).assert_failure(
        expected_error_re=re.escape(
            "The locked version of requests in {lock} is {version} which does not satisfy the "
            "'requests!={version}' requirement.".format(lock=lock, version=requests_version)
        )
    )


def test_lock_subset_extra(
    tmpdir,  # type: Tempdir
    lock,  # type: str
):
    # type: (...) -> None

    subset_lock = tmpdir.join("subset.lock")
    run_pex3(
        "lock", "subset", "--lock", lock, "pex[management]", "--indent", "2", "-o", subset_lock
    ).assert_success()
    subset_lockfile, subset_locked_reqs = index(subset_lock)
    assert SortedTuple([Requirement.parse("pex[management]")]) == subset_lockfile.requirements
    assert {ProjectName("pex"), ProjectName("psutil")} == set(subset_locked_reqs)

    run_pex3(
        "lock", "subset", "--lock", lock, "psutil", "--indent", "2", "-o", subset_lock
    ).assert_success()
    subset_lockfile, subset_locked_reqs = index(subset_lock)
    assert SortedTuple([Requirement.parse("psutil")]) == subset_lockfile.requirements
    assert {ProjectName("psutil")} == set(subset_locked_reqs)


def test_lock_subset_extra_miss(
    tmpdir,  # type: Tempdir
    lock,  # type: str
):
    # type: (...) -> None

    run_pex3("lock", "subset", "--lock", lock, "subprocess32").assert_failure(
        expected_error_re=re.escape(
            "There is no lock entry for subprocess32 in {lock} to satisfy the 'subprocess32' "
            "requirement.".format(lock=lock)
        )
    )
