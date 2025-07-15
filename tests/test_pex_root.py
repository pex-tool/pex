# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os

from pex.common import touch
from pex.pex_root import can_write_dir
from testing.pytest_utils.tmp import Tempdir


def test_can_write_dir_writeable_perms(tmpdir):
    # type: (Tempdir) -> None

    assert can_write_dir(tmpdir.path)

    path = tmpdir.join("does", "not", "exist", "yet")
    assert can_write_dir(path)
    touch(path)
    assert not can_write_dir(path), "Should not be able to write to a file."


def test_can_write_dir_unwriteable_perms(tmpdir):
    # type: (Tempdir) -> None

    no_perms_path = tmpdir.join("no_perms")
    os.mkdir(no_perms_path, 0o444)
    assert not can_write_dir(no_perms_path)

    path_that_does_not_exist_yet = os.path.join(no_perms_path, "does", "not", "exist", "yet")
    assert not can_write_dir(path_that_does_not_exist_yet)

    os.chmod(no_perms_path, 0o744)
    assert can_write_dir(no_perms_path)
    assert can_write_dir(path_that_does_not_exist_yet)
