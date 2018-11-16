# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex import interpreter
from pex.compatibility import PY3
from pex.testing import IS_PYPY, PY27, PY35, ensure_python_interpreter

try:
  from mock import patch
except ImportError:
  from unittest.mock import patch


def tuple_from_version(version_string):
  return tuple(int(component) for component in version_string.split('.'))


class TestPythonInterpreter(object):
  def test_all_does_not_raise_with_empty_path_envvar(self):
    """ additionally, tests that the module does not raise at import """
    with patch.dict(os.environ, clear=True):
      if PY3:
        import importlib
        importlib.reload(interpreter)
      else:
        reload(interpreter)
      interpreter.PythonInterpreter.all()

  TEST_INTERPRETER1_VERSION = PY27
  TEST_INTERPRETER1_VERSION_TUPLE = tuple_from_version(TEST_INTERPRETER1_VERSION)

  TEST_INTERPRETER2_VERSION = PY35
  TEST_INTERPRETER2_VERSION_TUPLE = tuple_from_version(TEST_INTERPRETER2_VERSION)

  @pytest.fixture
  def test_interpreter1(self):
    return ensure_python_interpreter(self.TEST_INTERPRETER1_VERSION)

  @pytest.fixture
  def test_interpreter2(self):
    return ensure_python_interpreter(self.TEST_INTERPRETER2_VERSION)

  @pytest.mark.skipif(IS_PYPY)
  def test_interpreter_versioning(self, test_interpreter1):
    py_interpreter = interpreter.PythonInterpreter.from_binary(test_interpreter1)
    assert py_interpreter.identity.version == self.TEST_INTERPRETER1_VERSION_TUPLE

  @pytest.mark.skipif(IS_PYPY)
  def test_interpreter_caching(self, test_interpreter1, test_interpreter2):
    py_interpreter1 = interpreter.PythonInterpreter.from_binary(test_interpreter1)
    py_interpreter2 = interpreter.PythonInterpreter.from_binary(test_interpreter2)
    assert py_interpreter1 is not py_interpreter2
    assert py_interpreter2.identity.version == self.TEST_INTERPRETER2_VERSION_TUPLE

    py_interpreter3 = interpreter.PythonInterpreter.from_binary(test_interpreter1)
    assert py_interpreter1 is py_interpreter3
