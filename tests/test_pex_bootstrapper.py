# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest
from twitter.common.contextutil import temporary_dir

from pex.common import open_zip
from pex.pex_bootstrapper import _find_compatible_interpreter_in_pex_python_path, get_pex_info
from pex.testing import write_simple_pex

try:
  import mock
except ImportError:
  import unittest.mock as mock




@pytest.fixture
def py27_interpreter():
  mock_interpreter = mock.MagicMock()
  mock_interpreter.binary = '/path/to/python2.7'
  mock_interpreter.version = (2, 7, 10)
  mock_interpreter.__lt__ = lambda x, y: x.version < y.version
  return mock_interpreter


@pytest.fixture
def py36_interpreter():
  mock_interpreter = mock.MagicMock()
  mock_interpreter.binary = '/path/to/python3.6'
  mock_interpreter.version = (3, 6, 3)
  mock_interpreter.__lt__ = lambda x, y: x.version < y.version
  return mock_interpreter


def mock_get_python_interpreter(binary):
  """Patch function for resolving PythonInterpreter mock objects from Pex Python Path"""
  if '3' in binary:
    return py36_interpreter()
  elif '2' in binary:
    return py27_interpreter()


def mock_matches(interpreter, filters, meet_all_constraints):
  """Patch function for determining if the supplied interpreter complies with the filters"""
  if '>3' in filters:
    return True if interpreter.version > (3, 0, 0) else False
  elif '<3' in filters:
    return True if interpreter.version < (3, 0, 0) else False
  elif '>=2.7' in filters:
    return True if interpreter.version > (2, 7, 0) else False
  else:
    return False


def test_get_pex_info():
  with temporary_dir() as td:
    pb = write_simple_pex(td, 'print("hello world!")')
    pex_path = os.path.join(td, 'hello_world.pex')
    pb.build(pex_path)

    # from zip
    pex_info = get_pex_info(pex_path)

    with temporary_dir() as pex_td:
      with open_zip(pex_path, 'r') as zf:
        zf.extractall(pex_td)

      # from dir
      pex_info_2 = get_pex_info(pex_td)

      # same when encoded
      assert pex_info.dump() == pex_info_2.dump()


@mock.patch('pex.interpreter_constraints._matches', side_effect=mock_matches)
@mock.patch('pex.pex_bootstrapper._get_python_interpreter', side_effect=mock_get_python_interpreter)
@pytest.mark.skipif("hasattr(sys, 'pypy_version_info')")
def test_find_compatible_interpreter_in_python_path(mock_get_python_interpreter, mock_matches):
  pex_python_path = ':'.join(['/path/to/python2.7', '/path/to/python3.6'])

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '>3')
  assert interpreter.binary == '/path/to/python3.6'

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '<3')
  assert interpreter.binary == '/path/to/python2.7'

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '<2')
  assert interpreter is None

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '>4')
  assert interpreter is None
