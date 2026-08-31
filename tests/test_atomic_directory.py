# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import os
import re
from contextlib import contextmanager
from warnings import WarningMessage

import pytest

from pex.atomic_directory import AtomicDirectory, _atomic_directory, atomic_directory
from pex.common import touch
from pex.pex_warnings import PEXWarning
from pex.typing import TYPE_CHECKING
from testing.pytest_utils.tmp import Tempdir

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]

if TYPE_CHECKING:
    from typing import Iterator, List, Optional, Type


@contextmanager
def maybe_raises(exception=None):
    # type: (Optional[Type[Exception]]) -> Iterator[None]
    @contextmanager
    def noop():
        yield

    context = noop() if exception is None else pytest.raises(exception)
    with context:
        yield


def atomic_directory_finalize_test(errno, expect_raises=None):
    # type: (int, Optional[Type[Exception]]) -> None
    with mock.patch("pex.fs.safe_rename", spec_set=True, autospec=True) as mock_rename:
        mock_rename.side_effect = OSError(errno, os.strerror(errno))
        with maybe_raises(expect_raises):
            AtomicDirectory("to.dir").finalize()


def test_atomic_directory_finalize_eexist():
    # type: () -> None
    atomic_directory_finalize_test(errno.EEXIST)


def test_atomic_directory_finalize_enotempty():
    # type: () -> None
    atomic_directory_finalize_test(errno.ENOTEMPTY)


def test_atomic_directory_finalize_eperm():
    # type: () -> None
    atomic_directory_finalize_test(errno.EPERM, expect_raises=OSError)


def test_atomic_directory_empty_workdir_finalize(tmpdir):
    # type: (Tempdir) -> None

    sandbox = tmpdir.join("sandbox")
    target_dir = os.path.join(sandbox, "target_dir")
    assert not os.path.exists(target_dir)

    with atomic_directory(target_dir) as atomic_dir:
        assert not atomic_dir.is_finalized()
        assert target_dir == atomic_dir.target_dir
        assert os.path.exists(atomic_dir.work_dir)
        assert os.path.isdir(atomic_dir.work_dir)
        assert [] == os.listdir(atomic_dir.work_dir)

        touch(os.path.join(atomic_dir.work_dir, "created"))

        assert not os.path.exists(target_dir)

    assert not os.path.exists(atomic_dir.work_dir), "The work_dir should always be cleaned up."
    assert os.path.exists(os.path.join(target_dir, "created"))


def test_atomic_directory_empty_workdir_failure(tmpdir):
    # type: (Tempdir) -> None

    class SimulatedRuntimeError(RuntimeError):
        pass

    sandbox = tmpdir.join("sandbox")
    target_dir = os.path.join(sandbox, "target_dir")
    with pytest.raises(SimulatedRuntimeError):
        with atomic_directory(target_dir) as atomic_dir:
            assert not atomic_dir.is_finalized()
            touch(os.path.join(atomic_dir.work_dir, "created"))
            raise SimulatedRuntimeError()

    assert not os.path.exists(  # type: ignore[unreachable]
        atomic_dir.work_dir
    ), "The work_dir should always be cleaned up."
    assert not os.path.exists(target_dir), (
        "When the context raises the work_dir it was given should not be moved to the "
        "target_dir."
    )


def test_atomic_directory_empty_workdir_finalized(tmpdir):
    # type: (Tempdir) -> None

    with atomic_directory(tmpdir.path) as work_dir:
        assert work_dir.is_finalized(), "When the target_dir exists no work_dir should be created."


def test_atomic_directory_locked_mode():
    # type: () -> None

    assert AtomicDirectory("unlocked").work_dir != AtomicDirectory("unlocked").work_dir
    assert (
        AtomicDirectory("locked", locked=True).work_dir
        == AtomicDirectory("locked", locked=True).work_dir
    )


def test_long_file_name_issue_2087():
    # type: () -> None

    atomic_directory = AtomicDirectory(
        "/tmp/pycryptodome-3.16.0-cp35-abi3-manylinux_2_5_x86_64.manylinux1_x86_64."
        "manylinux_2_12_x86_64",
        locked=False,
    )
    assert re.match(
        r"pycryptodome-3\.16\.0-cp35-abi3-manylinux_2_5_x86_64\.manylinux1_x86_64\."
        r"manylinux_2_12_x86_64\.[a-f0-9]+.work",
        os.path.basename(atomic_directory.work_dir),
    ), "Expected shorter directory names to use a workdir with the target dir as a prefix."

    atomic_directory = AtomicDirectory(
        "/tmp/pycryptodome-3.16.0-cp35-abi3-manylinux_2_5_x86_64.manylinux1_x86_64."
        "manylinux_2_12_x86_64.manylinux2010_x86_64.whl",
        locked=False,
    )
    assert "/tmp" == os.path.dirname(
        atomic_directory.work_dir
    ), "Expected the workdir to be co-located with the target dir to ensure atomic rename works."
    assert 143 == len(
        os.path.basename(atomic_directory.work_dir)
    ), "Expected longer directory names to use a workdir that is 143 characters in length."
    assert re.match(
        r"^pycryptodome-3\.16\.0-cp35-abi3-manylinux_2_5_x86_64\.manylinux1_x86_64\.manylin"
        r"\.\.\.[a-f0-9]{64}$",
        os.path.basename(atomic_directory.work_dir),
    ), "Expected longer directory names to retain their prefix with a `...<hash>` suffix."


def assert_warnings(
    warned,  # type: List[WarningMessage]
    expected,  # type: List[str]
):
    # type: (...) -> None
    actual = []  # type: List[str]
    for warning in warned:
        assert isinstance(warning.message, PEXWarning)
        actual.append(":".join(warning.message.args[0].split(":")[4:]).strip())

    assert len(expected) == len(actual)
    for expected_re, actual_msg in zip(expected, actual):
        assert re.match(expected_re, actual_msg)


def test_kill_locked_partial_cleanup_re_use(tmpdir):
    # type: (Tempdir) -> None

    cache_dir = tmpdir.join("cache")
    proof1 = os.path.join(cache_dir, "proof1")
    assert not os.path.exists(proof1)
    proof2 = os.path.join(cache_dir, "proof2")
    assert not os.path.exists(proof2)

    atomic_dir = AtomicDirectory(target_dir=cache_dir, locked=True)
    initial_work_dir = atomic_dir.work_dir
    assert not os.path.exists(proof1)
    assert not os.path.exists(proof2)

    os.makedirs(initial_work_dir)
    touch(os.path.join(initial_work_dir, "proof1"))

    with pytest.warns(PEXWarning) as record:
        with _atomic_directory(atomic_dir):
            if not atomic_dir.is_finalized():
                assert initial_work_dir == atomic_dir.work_dir
                touch(os.path.join(atomic_dir.work_dir, "proof1"))
                touch(os.path.join(atomic_dir.work_dir, "proof2"))

    assert_warnings(
        record.list,
        [
            re.escape(
                "After obtaining an exclusive lock on {lock_file}, failed to establish a work "
                "directory at {work_dir} due to: [Errno 17] File exists: '{work_dir}'".format(
                    lock_file=atomic_dir.lockfile, work_dir=initial_work_dir
                )
            ),
            re.escape(
                "Continuing to forcibly re-create the work directory at {work_dir}.".format(
                    work_dir=initial_work_dir
                )
            ),
        ],
    )
    assert os.path.exists(proof1)
    assert os.path.exists(proof2)


def test_kill_locked_partial_cleanup_fail_use_random(tmpdir):
    # type: (Tempdir) -> None

    cache_dir = tmpdir.join("cache")
    proof1 = os.path.join(cache_dir, "proof1")
    assert not os.path.exists(proof1)
    proof2 = os.path.join(cache_dir, "proof2")
    assert not os.path.exists(proof2)

    atomic_dir = AtomicDirectory(target_dir=cache_dir, locked=True)
    initial_work_dir = atomic_dir.work_dir
    assert not os.path.exists(proof1)
    assert not os.path.exists(proof2)

    os.makedirs(initial_work_dir)
    touch(os.path.join(initial_work_dir, "proof1"))
    os.chmod(initial_work_dir, 0o444)
    try:
        with pytest.warns(PEXWarning) as record:
            with _atomic_directory(atomic_dir):
                if not atomic_dir.is_finalized():
                    assert initial_work_dir != atomic_dir.work_dir
                    touch(os.path.join(atomic_dir.work_dir, "proof1"))
                    touch(os.path.join(atomic_dir.work_dir, "proof2"))
    finally:
        os.chmod(initial_work_dir, 0o755)

    assert_warnings(
        record.list,
        [
            re.escape(
                "After obtaining an exclusive lock on {lock_file}, failed to establish a work "
                "directory at {work_dir} due to: [Errno 17] File exists: '{work_dir}'".format(
                    lock_file=atomic_dir.lockfile, work_dir=initial_work_dir
                )
            ),
            re.escape(
                "Continuing to forcibly re-create the work directory at {work_dir}.".format(
                    work_dir=initial_work_dir
                )
            ),
            r"{msg}.*".format(
                msg=re.escape(
                    "Failed to forcibly re-create the work directory at {work_dir}: "
                    "[Errno 13] Permission denied: '".format(work_dir=initial_work_dir)
                )
            ),
            re.escape(
                "Using new random workdir instead: {work_dir}.".format(work_dir=atomic_dir.work_dir)
            ),
        ],
    )
    assert os.path.exists(proof1)
    assert os.path.exists(proof2)
