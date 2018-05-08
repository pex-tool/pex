# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex import interpreter
from pex.testing import IS_PYPY, ensure_python_interpreter

try:
  from mock import patch
except ImportError:
  from unittest.mock import patch


class TestPythonInterpreter(object):

  @pytest.mark.skipif('sys.version_info >= (3,0)')
  def test_all_does_not_raise_with_empty_path_envvar(self):
    """ additionally, tests that the module does not raise at import """
    with patch.dict(os.environ, clear=True):
      reload(interpreter)
      interpreter.PythonInterpreter.all()

  @pytest.mark.skipif(IS_PYPY)
  def test_interpreter_versioning(self):
    test_version_tuple = (2, 7, 10)
    test_version = '.'.join(str(x) for x in test_version_tuple)
    test_interpreter = ensure_python_interpreter(test_version)
    py_interpreter = interpreter.PythonInterpreter.from_binary(test_interpreter)
    assert py_interpreter.identity.version == test_version_tuple
