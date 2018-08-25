# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import zipimport

import pkg_resources
import pytest

from pex.finders import ChainedFinder
from pex.finders import _add_finder as add_finder
from pex.finders import _remove_finder as remove_finder
from pex.finders import find_eggs_in_zip, get_entry_point_from_console_script, get_script_from_egg

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


def test_get_script_from_egg():
  # Make sure eggs without scripts don't cause errors
  dists = list(
    find_eggs_in_zip(
      zipimport.zipimporter('./tests/example_packages/Flask_Cache-0.13.1-py2.7.egg'),
      './tests/example_packages/Flask_Cache-0.13.1-py2.7.egg',
      only=True))

  assert len(dists) == 1

  (location, content) = get_script_from_egg('non_existent_script', dists[0])

  assert location is None
  assert content is None


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
  assert 'bob.main:run' == get_entry_point_from_console_script('bob', dists)


def test_get_entry_point_from_console_script_conflict():
  dists = [FakeDist(key='bob', console_script_entry='bob= bob.main:run'),
           FakeDist(key='fake', console_script_entry='bob =bob.main:run')]
  with pytest.raises(RuntimeError):
    get_entry_point_from_console_script('bob', dists)


def test_get_entry_point_from_console_script_dne():
  dists = [FakeDist(key='bob', console_script_entry='bob= bob.main:run'),
           FakeDist(key='fake', console_script_entry='bob =bob.main:run')]
  assert None is get_entry_point_from_console_script('jane', dists)
