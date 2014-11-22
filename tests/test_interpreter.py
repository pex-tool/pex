# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex import interpreter

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
