# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import contextlib
import errno
import os
from contextlib import contextmanager

import pytest

from pex.common import Chroot, PermPreservingZipFile, chmod_plus_x, rename_if_empty, touch
from pex.testing import temporary_dir

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


def extract_perms(path):
  return oct(os.stat(path).st_mode)


@contextlib.contextmanager
def zip_fixture():
  with temporary_dir() as target_dir:
    one = os.path.join(target_dir, 'one')
    touch(one)

    two = os.path.join(target_dir, 'two')
    touch(two)
    chmod_plus_x(two)

    assert extract_perms(one) != extract_perms(two)

    zip_file = os.path.join(target_dir, 'test.zip')
    with contextlib.closing(PermPreservingZipFile(zip_file, 'w')) as zf:
      zf.write(one, 'one')
      zf.write(two, 'two')

    yield zip_file, os.path.join(target_dir, 'extract'), one, two


def test_perm_preserving_zipfile_extractall():
  with zip_fixture() as (zip_file, extract_dir, one, two):
    with contextlib.closing(PermPreservingZipFile(zip_file)) as zf:
      zf.extractall(extract_dir)

      assert extract_perms(one) == extract_perms(os.path.join(extract_dir, 'one'))
      assert extract_perms(two) == extract_perms(os.path.join(extract_dir, 'two'))


def test_perm_preserving_zipfile_extract():
  with zip_fixture() as (zip_file, extract_dir, one, two):
    with contextlib.closing(PermPreservingZipFile(zip_file)) as zf:
      zf.extract('one', path=extract_dir)
      zf.extract('two', path=extract_dir)

      assert extract_perms(one) == extract_perms(os.path.join(extract_dir, 'one'))
      assert extract_perms(two) == extract_perms(os.path.join(extract_dir, 'two'))


def assert_chroot_perms(copyfn):
  with temporary_dir() as src:
    one = os.path.join(src, 'one')
    touch(one)

    two = os.path.join(src, 'two')
    touch(two)
    chmod_plus_x(two)

    with temporary_dir() as dst:
      chroot = Chroot(dst)
      copyfn(chroot, one, 'one')
      copyfn(chroot, two, 'two')
      assert extract_perms(one) == extract_perms(os.path.join(chroot.path(), 'one'))
      assert extract_perms(two) == extract_perms(os.path.join(chroot.path(), 'two'))

      zip_path = os.path.join(src, 'chroot.zip')
      chroot.zip(zip_path)
      with temporary_dir() as extract_dir:
        with contextlib.closing(PermPreservingZipFile(zip_path)) as zf:
          zf.extractall(extract_dir)

          assert extract_perms(one) == extract_perms(os.path.join(extract_dir, 'one'))
          assert extract_perms(two) == extract_perms(os.path.join(extract_dir, 'two'))


def test_chroot_perms_copy():
  assert_chroot_perms(Chroot.copy)


def test_chroot_perms_link_same_device():
  assert_chroot_perms(Chroot.link)


def test_chroot_perms_link_cross_device():
  with mock.patch('os.link', spec_set=True, autospec=True) as mock_link:
    expected_errno = errno.EXDEV
    mock_link.side_effect = OSError(expected_errno, os.strerror(expected_errno))

    assert_chroot_perms(Chroot.link)
