# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import os
from contextlib import contextmanager

import pytest

from pex.common import rename_if_empty

try:
  from unittest import mock
except ImportError:
  import mock


@contextmanager
def maybe_raises(exception=None):
  @contextmanager
  def noop():
    yield

  with (noop() if exception is None else pytest.raises(exception)):
    yield


def rename_if_empty_test(errno, expect_raises=None):
  with mock.patch('os.rename', spec_set=True, autospec=True) as mock_rename:
    mock_rename.side_effect = OSError(errno, os.strerror(errno))
    with maybe_raises(expect_raises):
      rename_if_empty('from.dir', 'to.dir')


def test_rename_if_empty_eexist():
  rename_if_empty_test(errno.EEXIST)


def test_rename_if_empty_enotempty():
  rename_if_empty_test(errno.ENOTEMPTY)


def test_rename_if_empty_eperm():
  rename_if_empty_test(errno.EPERM, expect_raises=OSError)
