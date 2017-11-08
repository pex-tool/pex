# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from twitter.common.contextutil import temporary_dir

from pex.common import open_zip
from pex.interpreter import PythonInterpreter
from pex.pex_bootstrapper import (
    _find_compatible_interpreters,
    _get_python_interpreter,
    get_pex_info
)
from pex.testing import ensure_python_interpreter, write_simple_pex


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


def test_find_compatible_interpreters():
  ensure_python_interpreter('2.7.10')
  ensure_python_interpreter('3.6.3')
  pex_python_path = ':'.join([os.getcwd() + '/.pyenv_test/versions/2.7.10/bin/python2.7',
                              os.getcwd() + '/.pyenv_test/versions/3.6.3/bin/python3.6'])

  interpreters = _find_compatible_interpreters(pex_python_path, ['>3'])
  assert interpreters[0].binary == pex_python_path.split(':')[1]

  interpreters = _find_compatible_interpreters(pex_python_path, ['<3'])
  assert interpreters[0].binary == pex_python_path.split(':')[0]

  interpreters = _find_compatible_interpreters(pex_python_path, ['<2'])
  assert not interpreters

  interpreters = _find_compatible_interpreters(pex_python_path, ['>4'])
  assert not interpreters

  # test fallback to PATH
  interpreters = _find_compatible_interpreters('', ['<3'])
  assert len(interpreters) > 0
  assert all([i.version < (3, 0, 0) for i in interpreters])
  assert 'pyenv_test' not in ' '.join([i.binary for i in interpreters])

  interpreters = _find_compatible_interpreters('', ['>3'])
  assert len(interpreters) > 0
  assert all([i.version > (3, 0, 0) for i in interpreters])
  assert 'pyenv_test' not in ' '.join([i.binary for i in interpreters])


def test_get_python_interpreter():
  ensure_python_interpreter('2.7.10')
  good_binary = os.getcwd() + '/.pyenv_test/versions/2.7.10/bin/python'
  res1 = _get_python_interpreter(good_binary).binary
  res2 = PythonInterpreter.from_binary(good_binary).binary
  assert res1 == res2
  assert _get_python_interpreter('bad/path/to/binary/Python') is None
