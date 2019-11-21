# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

import pytest

from pex.pep425tags import get_abbr_impl, get_abi_tag, get_impl_ver
from pex.platforms import Platform

try:
  from mock import patch
except ImportError:
  from unittest.mock import patch


EXPECTED_BASE = [('py27', 'none', 'any'), ('py2', 'none', 'any')]


def test_platform():
  assert Platform('linux-x86_64', 'cp', '27', 'mu') == ('linux_x86_64', 'cp', '27', 'cp27mu')
  assert str(
    Platform('linux-x86_64', 'cp', '27', 'm')
  ) == 'linux_x86_64-cp-27-cp27m'


def test_platform_create():
  assert Platform.create('linux-x86_64-cp-27-cp27mu') == ('linux_x86_64', 'cp', '27', 'cp27mu')
  assert Platform.create('linux-x86_64-cp-27-mu') == ('linux_x86_64', 'cp', '27', 'cp27mu')
  assert Platform.create(
    'macosx-10.4-x86_64-cp-27-m') == ('macosx_10_4_x86_64', 'cp', '27', 'cp27m')


def test_platform_create_bad_platform_missing_fields():
  with pytest.raises(Platform.InvalidPlatformError):
    Platform.create('linux-x86_64')


def test_platform_create_bad_platform_empty_fields():
  with pytest.raises(Platform.InvalidPlatformError):
    Platform.create('linux-x86_64-cp--cp27mu')


def test_platform_create_noop():
  existing = Platform.create('linux-x86_64-cp-27-mu')
  assert Platform.create(existing) == existing


def assert_tags(platform, expected_tags):
  maybe_foreign_platform = Platform.create(platform)
  if Platform.current() == maybe_foreign_platform:
    # We can only assert tags when we know the local interpreter is not being consulted, since local
    # consults will pick up things that may vary, like manylinux{1,2010,2014} support.
    pytest.skip('Skipping test of supported tags on local platform {}'.format(platform))

  tags = maybe_foreign_platform.supported_tags()
  for expected_tag in expected_tags:
    assert expected_tag in tags


def test_platform_supported_tags_linux():
  assert_tags(
    'linux-x86_64-cp-27-mu',
    EXPECTED_BASE + [('cp27', 'cp27mu', 'linux_x86_64')]
  )


def test_platform_supported_tags_osx_minimal():
  impl_tag = "{}{}".format(get_abbr_impl(), get_impl_ver())
  assert_tags(
    'macosx-10.5-x86_64-{}-{}-{}'.format(get_abbr_impl(), get_impl_ver(), get_abi_tag()),
    [
      (impl_tag, 'none', 'any'),
      ('py%s' % sys.version_info[0], 'none', 'any'),
      (impl_tag, get_abi_tag(), 'macosx_10_5_x86_64')
    ]
  )


def test_platform_supported_tags_osx_full():
  assert_tags(
    'macosx-10.12-x86_64-cp-27-m',
    EXPECTED_BASE + [
      ('cp27', 'cp27m', 'macosx_10_4_intel'),
      ('cp27', 'cp27m', 'macosx_10_5_x86_64'),
      ('cp27', 'cp27m', 'macosx_10_6_x86_64'),
      ('cp27', 'cp27m', 'macosx_10_7_x86_64'),
      ('cp27', 'cp27m', 'macosx_10_8_x86_64'),
      ('cp27', 'cp27m', 'macosx_10_9_x86_64'),
      ('cp27', 'cp27m', 'macosx_10_10_x86_64'),
      ('cp27', 'cp27m', 'macosx_10_11_x86_64'),
      ('cp27', 'cp27m', 'macosx_10_12_x86_64'),
    ]
  )


def test_pypy_abi_prefix():
  assert_tags(
    'linux-x86_64-pp-260-pypy_41',
    [
      ('pp260', 'pypy_41', 'linux_x86_64'),
    ]
  )


@patch('pex.pep425tags.get_extension_suffixes', lambda: ['.abi3.so'])
def test_platform_supported_tags_abi3():
  assert_tags(
    'linux-x86_64-cp-37-m',
    [
      ('cp37', 'cp37m', 'linux_x86_64'),
      ('cp37', 'abi3', 'linux_x86_64'),
      ('cp37', 'none', 'linux_x86_64'),
      ('cp36', 'abi3', 'linux_x86_64'),
      ('cp35', 'abi3', 'linux_x86_64'),
      ('cp34', 'abi3', 'linux_x86_64'),
      ('cp33', 'abi3', 'linux_x86_64'),
      ('cp32', 'abi3', 'linux_x86_64'),
      ('py3', 'none', 'linux_x86_64'),
      ('cp37', 'none', 'any'),
      ('cp3', 'none', 'any'),
      ('py37', 'none', 'any'),
      ('py3', 'none', 'any'),
      ('py36', 'none', 'any'),
      ('py35', 'none', 'any'),
      ('py34', 'none', 'any'),
      ('py33', 'none', 'any'),
      ('py32', 'none', 'any'),
      ('py31', 'none', 'any'),
      ('py30', 'none', 'any'),
    ]
  )


@patch('pex.pep425tags.get_extension_suffixes', lambda: [])
def test_platform_supported_tags_no_abi3():
  assert_tags(
    'linux-x86_64-cp-37-m',
    [
      ('cp37', 'cp37m', 'linux_x86_64'),
      ('cp37', 'none', 'linux_x86_64'),
      ('py3', 'none', 'linux_x86_64'),
      ('cp37', 'none', 'any'),
      ('cp3', 'none', 'any'),
      ('py37', 'none', 'any'),
      ('py3', 'none', 'any'),
      ('py36', 'none', 'any'),
      ('py35', 'none', 'any'),
      ('py34', 'none', 'any'),
      ('py33', 'none', 'any'),
      ('py32', 'none', 'any'),
      ('py31', 'none', 'any'),
      ('py30', 'none', 'any'),
    ]
  )


def test_platform_current_tags():
  local_platform = str(Platform.current())
  assert Platform.current().supported_tags() == Platform.create(local_platform).supported_tags()
