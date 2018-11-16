# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import zipimport

import pytest

import pex.third_party.pkg_resources as pkg_resources
from pex.compatibility import to_bytes
from pex.finders import ChainedFinder
from pex.finders import _add_finder as add_finder
from pex.finders import _remove_finder as remove_finder
from pex.finders import (
    find_wheels_in_zip,
    get_entry_point_from_console_script,
    get_script_from_egg,
    get_script_from_whl
)

try:
  import mock
except ImportError:
  from unittest import mock


def test_chained_finder():
  def finder1(importer, path_item, only=False):
    for foo in ('foo', 'bar'):
      yield foo

  def finder2(importer, path_item, only=False):
    yield 'baz'

  cf = ChainedFinder([finder1])
  assert list(cf(None, None)) == ['foo', 'bar']

  cf = ChainedFinder([finder1, finder2])
  assert list(cf(None, None)) == ['foo', 'bar', 'baz']


GET_FINDER = 'pex.finders._get_finder'
REGISTER_FINDER = 'pex.finders.pkg_resources.register_finder'


def test_add_new_finder():
  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      mock_get_finder.return_value = None
      add_finder('foo', 'bar')
      mock_register_finder.assert_called_with('foo', 'bar')


def test_append_finder():
  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      mock_get_finder.return_value = 'bar'
      add_finder('foo', 'baz')
      mock_register_finder.assert_called_with('foo', ChainedFinder(['bar', 'baz']))

  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      mock_get_finder.return_value = ChainedFinder(['bar'])
      add_finder('foo', 'baz')
      mock_register_finder.assert_called_with('foo', ChainedFinder(['bar', 'baz']))


def test_remove_finder():
  # wasn't registered
  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      mock_get_finder.return_value = None
      remove_finder('foo', 'baz')
      assert not mock_register_finder.called

  # was registered but we're asking for the wrong one
  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      mock_get_finder.return_value = ChainedFinder(['bar'])
      remove_finder('foo', 'baz')
      assert not mock_register_finder.called

  # was registered but we're asking for the wrong one
  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      cf = ChainedFinder(['bar', 'baz', 'bak'])
      mock_get_finder.return_value = cf
      remove_finder('foo', 'baz')
      assert cf.finders == ['bar', 'bak']
      assert not mock_register_finder.called

  # was registered but we're asking for the wrong one
  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      cf = ChainedFinder(['bar', 'baz'])
      mock_get_finder.return_value = cf
      remove_finder('foo', 'baz')
      mock_register_finder.assert_called_with('foo', 'bar')

  # was registered but we're asking for the wrong one
  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      mock_get_finder.return_value = 'bar'
      remove_finder('foo', 'bar')
      mock_register_finder.assert_called_with('foo', pkg_resources.find_nothing)

  # was registered but we're asking for the wrong one
  with mock.patch(GET_FINDER) as mock_get_finder:
    with mock.patch(REGISTER_FINDER) as mock_register_finder:
      mock_get_finder.return_value = ChainedFinder(['bar'])
      remove_finder('foo', 'bar')
      mock_register_finder.assert_called_with('foo', pkg_resources.find_nothing)


# Ensure our vendored setuptools carries a pkg_resources.find_eggs_in_zip that works as expected.
# In the past we could not rely on a modern setuptools with a fully working zipped egg finder; so we
# rolled our own and these tests confirmed our implementation worked. We retain the tests to make
# sure setuptools doesn't backslide.
def test_get_script_from_egg_with_no_scripts():
  # Make sure eggs without scripts don't cause errors.
  egg_path = './tests/example_packages/Flask_Cache-0.13.1-py2.7.egg'
  dists = list(pkg_resources.find_eggs_in_zip(zipimport.zipimporter(egg_path), egg_path, only=True))
  assert len(dists) == 1

  dist = dists[0]
  assert (None, None) == get_script_from_egg('non_existent_script', dist)


def test_get_script_from_egg():
  egg_path = './tests/example_packages/eno-0.0.17-py2.7.egg'
  dists = list(pkg_resources.find_eggs_in_zip(zipimport.zipimporter(egg_path), egg_path, only=True))
  assert len(dists) == 1

  dist = dists[0]

  location, content = get_script_from_egg('run_eno_server', dist)
  assert os.path.join(egg_path, 'EGG-INFO/scripts/run_eno_server') == location
  assert content.startswith('#!'), 'Expected a `scripts` style script with shebang.'

  assert (None, None) == get_script_from_egg('non_existent_script', dist)


# In-part, tests a bug where the wheel distribution name has dashes as reported in:
#   https://github.com/pantsbuild/pex/issues/443
#   https://github.com/pantsbuild/pex/issues/551
def test_get_script_from_whl():
  whl_path = './tests/example_packages/aws_cfn_bootstrap-1.4-py2-none-any.whl'
  dists = list(find_wheels_in_zip(zipimport.zipimporter(whl_path), whl_path))
  assert len(dists) == 1

  dist = dists[0]
  assert 'aws-cfn-bootstrap' == dist.project_name

  script_path, script_content = get_script_from_whl('cfn-signal', dist)
  assert os.path.join(whl_path, 'aws_cfn_bootstrap-1.4.data/scripts/cfn-signal') == script_path
  assert script_content.startswith(to_bytes('#!')), 'Expected a `scripts`-style script w/shebang.'

  assert (None, None) == get_script_from_whl('non_existent_script', dist)


class FakeDist(object):
  def __init__(self, key, console_script_entry):
    self.key = key
    script = console_script_entry.split('=')[0].strip()
    self._entry_map = {'console_scripts': {script: console_script_entry}}

  def get_entry_map(self):
    return self._entry_map


def test_get_entry_point_from_console_script():
  dists = [FakeDist(key='fake', console_script_entry='bob= bob.main:run'),
           FakeDist(key='fake', console_script_entry='bob =bob.main:run')]

  dist, entrypoint = get_entry_point_from_console_script('bob', dists)
  assert 'bob.main:run' == entrypoint
  assert dist in dists


def test_get_entry_point_from_console_script_conflict():
  dists = [FakeDist(key='bob', console_script_entry='bob= bob.main:run'),
           FakeDist(key='fake', console_script_entry='bob =bob.main:run')]
  with pytest.raises(RuntimeError):
    get_entry_point_from_console_script('bob', dists)


def test_get_entry_point_from_console_script_dne():
  dists = [FakeDist(key='bob', console_script_entry='bob= bob.main:run'),
           FakeDist(key='fake', console_script_entry='bob =bob.main:run')]
  assert (None, None) == get_entry_point_from_console_script('jane', dists)
