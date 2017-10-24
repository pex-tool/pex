# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

import pytest
from twitter.common.contextutil import temporary_dir

from pex.common import open_zip
from pex.interpreter import PythonInterpreter
from pex.pex_bootstrapper import _find_compatible_interpreter_in_pex_python_path, get_pex_info
from pex.testing import write_simple_pex


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


@pytest.mark.skipif("hasattr(sys, 'pypy_version_info')")
def test_find_compatible_interpreter_in_python_path():
  root_dir = os.getcwd()
  if sys.version_info[0] == 3:
    interpreters = [PythonInterpreter.from_binary(root_dir + '/.tox/py36/bin/python3.6'),
                    PythonInterpreter.from_binary(root_dir + '/.tox/py36-requests/bin/python3.6')]
  else:
    interpreters = [PythonInterpreter.from_binary(root_dir + '/.tox/py27/bin/python2.7'),
                    PythonInterpreter.from_binary(root_dir + '/.tox/py27-requests/bin/python2.7')]

  pex_python_path = ':'.join([interpreters[0].binary] + [interpreters[1].binary])

  if sys.version_info[0] == 3:
    interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '>3')
    # the returned interpreter will the rightmost interpreter in PPP if all versions are the same
    assert interpreter.binary == interpreters[1].binary
  else:
    interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '<3')
    assert interpreter.binary == interpreters[1].binary

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '<2')
  assert interpreter is None

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '>4')
  assert interpreter is None
