# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys

from pex.cli.commands import lockfile
from pex.cli.commands.lockfile import Lockfile
from pex.resolve.locked_resolve import LockedRequirement
from pex.resolve.testing import normalize_locked_resolve
from pex.sorted_tuple import SortedTuple
from pex.testing import IntegResults, make_env
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Any, Optional
else:
    from pex.third_party import attr


def run_pex3(
    *args,  # type: str
    **env  # type: Optional[str]
):
    # type: (...) -> IntegResults
    process = subprocess.Popen(
        args=[sys.executable, "-mpex.cli"] + list(args),
        env=make_env(**env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    return IntegResults(
        output=stdout.decode("utf-8"), error=stderr.decode("utf-8"), return_code=process.returncode
    )


def normalize_lockfile(
    lockfile,  # type: Lockfile
    skip_additional_artifacts=False,  # type: bool
    skip_urls=False,  # type: bool
):
    # type: (...) -> Lockfile
    return attr.evolve(
        lockfile,
        locked_resolves=SortedTuple(
            normalize_locked_resolve(
                locked_resolve,
                skip_additional_artifacts=skip_additional_artifacts,
                skip_urls=skip_urls,
            )
            for locked_resolve in lockfile.locked_resolves
        ),
        requirements=SortedTuple(),
    )


def test_create(tmpdir):
    # type: (Any) -> None

    lock_file = os.path.join(str(tmpdir), "requirements.lock.json")
    run_pex3("lock", "create", "ansicolors", "-o", lock_file).assert_success()

    requirements_file = os.path.join(str(tmpdir), "requirements.lock.txt")
    run_pex3("lock", "export", "-o", requirements_file, lock_file).assert_success()

    # We should get back the same lock given a lock as input mod comments (in particular the via
    # comment line which is sensitive to the source of the requirements)
    result = run_pex3("lock", "create", "-r", requirements_file)
    result.assert_success()
    assert normalize_lockfile(lockfile.load(lock_file)) == normalize_lockfile(
        lockfile.loads(result.output)
    )


def test_create_style(tmpdir):
    # type: (Any) -> None

    def create_lock(style):
        # type: (str) -> LockedRequirement
        lock_file = os.path.join(str(tmpdir), "{}.lock".format(style))
        run_pex3(
            "lock", "create", "ansicolors==1.1.8", "-o", lock_file, "--style", style
        ).assert_success()
        lock = lockfile.load(lock_file)
        assert 1 == len(lock.locked_resolves)
        locked_resolve = lock.locked_resolves[0]
        assert 1 == len(locked_resolve.locked_requirements)
        return locked_resolve.locked_requirements[0]

    assert not create_lock("strict").additional_artifacts

    # We should have 2 total artifacts for sources lock since we know ansicolors 1.1.8 provides
    # both a universal wheel and an sdist.
    assert 1 == len(create_lock("sources").additional_artifacts)
