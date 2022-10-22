# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.atomic_directory import FileLockStyle, _is_bsd_lock
from pex.testing import environment_as


def test_is_bsd_lock():
    # type: () -> None

    assert not _is_bsd_lock(
        lock_style=None
    ), "Expected the default lock style to be POSIX for maximum compatibility."
    assert not _is_bsd_lock(lock_style=FileLockStyle.POSIX)
    assert _is_bsd_lock(lock_style=FileLockStyle.BSD)

    # The hard-coded default is already POSIX, so setting the env var default changes nothing.
    with environment_as(_PEX_FILE_LOCK_STYLE="posix"):
        assert not _is_bsd_lock(lock_style=None)
        assert not _is_bsd_lock(lock_style=FileLockStyle.POSIX)
        assert _is_bsd_lock(lock_style=FileLockStyle.BSD)

    with environment_as(_PEX_FILE_LOCK_STYLE="bsd"):
        assert _is_bsd_lock(
            lock_style=None
        ), "Expected the default lock style to be taken from the environment when defined."
        assert not _is_bsd_lock(lock_style=FileLockStyle.POSIX)
        assert _is_bsd_lock(lock_style=FileLockStyle.BSD)
