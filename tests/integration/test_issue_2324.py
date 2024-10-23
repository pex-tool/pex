# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import itertools
import os.path

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import FileArtifact
from pex.resolve.lockfile import json_codec
from pex.resolve.resolved_requirement import Pin
from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3
from testing.pythonPI import skip_flit_core_39

if TYPE_CHECKING:
    from typing import Any


@skip_flit_core_39
def test_update_sdists_not_updated(tmpdir):
    # type: (Any) -> None

    constraints = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints, "w") as fp:
        print("ansicolors<1.1.8", file=fp)
        print("cowsay<6", file=fp)

    lock = os.path.join(str(tmpdir), "lock.json")

    def assert_lock(*pins):
        # type: (*Pin) -> None

        lockfile = json_codec.load(lock)
        assert 1 == len(lockfile.locked_resolves)
        locked_resolve = lockfile.locked_resolves[0]
        locked_requirements = {
            locked_req.pin: tuple(locked_req.iter_artifacts())
            for locked_req in locked_resolve.locked_requirements
        }
        assert set(pins) == set(locked_requirements)
        assert all(
            isinstance(artifact, FileArtifact) and artifact.is_source
            for artifact in itertools.chain.from_iterable(locked_requirements.values())
        )

    run_pex3(
        "lock",
        "create",
        "--no-wheel",
        "--constraints",
        constraints,
        "ansicolors",
        "cowsay",
        "--indent",
        "2",
        "-o",
        lock,
    ).assert_success()
    assert_lock(
        Pin(ProjectName("ansicolors"), Version("1.1.7")), Pin(ProjectName("cowsay"), Version("5.0"))
    )

    # N.B.: Pre-fix this test would lead to an artifact comparison assertion for cowsay, which is
    # expected to be unmodified by the lock update.
    #
    # E       Traceback (most recent call last):
    # E         File "/home/jsirois/dev/pex-tool/pex/pex/result.py", line 105, in catch
    # E           return func(*args, **kwargs)
    # E                  ^^^^^^^^^^^^^^^^^^^^^
    # E         File "/home/jsirois/dev/pex-tool/pex/pex/resolve/lockfile/updater.py", line 320, in update_resolve
    # E           assert updated_requirement.artifact == locked_requirement.artifact
    # E                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    # E       AssertionError
    # E       Encountered 1 error updating /tmp/pytest-of-jsirois/pytest-8/test_update_sdists_not_updated0/lock.json:
    # E       1.) cp311-cp311-manylinux_2_35_x86_64:
    run_pex3("lock", "update", "-v", "-p", "ansicolors<1.1.9", lock).assert_success()
    assert_lock(
        Pin(ProjectName("ansicolors"), Version("1.1.8")), Pin(ProjectName("cowsay"), Version("5.0"))
    )
