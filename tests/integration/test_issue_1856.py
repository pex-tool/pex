# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

from pex.resolve.lockfile import json_codec
from pex.typing import TYPE_CHECKING
from testing import PY38, ensure_python_interpreter, make_env
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


def test_os_name_spoofing(tmpdir):
    # type: (Any) -> None

    lock = os.path.join(str(tmpdir), "lock.json")

    create_lock_args = [
        "lock",
        "create",
        "--style",
        "universal",
        "--resolver-version",
        "pip-2020-resolver",
        "pywinpty==2.0.6; os_name == 'nt'",
        "--interpreter-constraint",
        "CPython<4,>=3.7.5",
        "--indent",
        "2",
        "-o",
        lock,
        "--target-system",
        "linux",
        "--target-system",
        "mac",
    ]

    # This ensures that, even if the machine has a functioning cargo / rust toolchain on the PATH,
    # it becomes non-functioning without altering the system permanently. This is needed to ensure
    # we can't build the pywinpty sdist to extract needed resolve metadata from it.
    #
    # For more info on this corner to reproducing the prior failure, see:
    #   https://github.com/pex-tool/pex/issues/1856#issuecomment-1193054493
    env = make_env(RUSTC=os.devnull)

    # The above attempt to get pywinpty dependency metadata by building the sdist requires a
    # CPython>=3.7.5 on the PATH which we arrange for if not already present here.
    if sys.version_info[:3] < (3, 7, 5):
        python_path = os.environ["PATH"].split(os.pathsep) + [ensure_python_interpreter(PY38)]
        create_lock_args.extend(["--python-path", os.pathsep.join(python_path)])

    run_pex3(*create_lock_args, env=env).assert_success()

    lockfile = json_codec.load(lockfile_path=lock)
    assert 1 == len(lockfile.locked_resolves)

    locked_resolve = lockfile.locked_resolves[0]
    assert 0 == len(locked_resolve.locked_requirements), (
        "Since we're not running on `os_name == 'nt'`, we shouldn't have been able to lock any "
        "requirements at all."
    )
