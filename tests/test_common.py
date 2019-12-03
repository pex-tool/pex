# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import errno
import os
from contextlib import contextmanager

import pytest

from pex.common import (
    AtomicDirectory,
    Chroot,
    PermPreservingZipFile,
    atomic_directory,
    chmod_plus_x,
    temporary_dir,
    touch
)

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


def atomic_directory_finalize_test(errno, expect_raises=None):
  with mock.patch('os.rename', spec_set=True, autospec=True) as mock_rename:
    mock_rename.side_effect = OSError(errno, os.strerror(errno))
    with maybe_raises(expect_raises):
      AtomicDirectory('to.dir').finalize()


def test_atomic_directory_finalize_eexist():
  atomic_directory_finalize_test(errno.EEXIST)


def test_atomic_directory_finalize_enotempty():
  atomic_directory_finalize_test(errno.ENOTEMPTY)


def test_atomic_directory_finalize_eperm():
  atomic_directory_finalize_test(errno.EPERM, expect_raises=OSError)


def test_atomic_directory_empty_workdir_finalize():
  with temporary_dir() as sandbox:
    target_dir = os.path.join(sandbox, 'target_dir')
    assert not os.path.exists(target_dir)

    with atomic_directory(target_dir) as work_dir:
      assert work_dir is not None
      assert os.path.exists(work_dir)
      assert os.path.isdir(work_dir)
      assert [] == os.listdir(work_dir)

      touch(os.path.join(work_dir, 'created'))

      assert not os.path.exists(target_dir)

    assert not os.path.exists(work_dir), 'The work_dir should always be cleaned up.'
    assert os.path.exists(os.path.join(target_dir, 'created'))


def test_atomic_directory_empty_workdir_failure():
  class SimulatedRuntimeError(RuntimeError):
    pass

  with temporary_dir() as sandbox:
    target_dir = os.path.join(sandbox, 'target_dir')
    with pytest.raises(SimulatedRuntimeError):
      with atomic_directory(target_dir) as work_dir:
        touch(os.path.join(work_dir, 'created'))
        raise SimulatedRuntimeError()

    assert not os.path.exists(work_dir), 'The work_dir should always be cleaned up.'
    assert not os.path.exists(target_dir), (
      'When the context raises the work_dir it was given should not be moved to the target_dir.'
    )


def test_atomic_directory_empty_workdir_finalized():
  with temporary_dir() as target_dir:
    with atomic_directory(target_dir) as work_dir:
      assert work_dir is None, 'When the target_dir exists no work_dir should be created.'


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
