# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest
from twitter.common.contextutil import temporary_dir

from pex.common import open_zip
from pex.interpreter import PythonInterpreter
from pex.pex_bootstrapper import find_compatible_interpreters, get_pex_info
from pex.testing import IS_PYPY, ensure_python_interpreter, write_simple_pex


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


@pytest.mark.skipif(IS_PYPY)
def test_find_compatible_interpreters():
  pex_python_path = ':'.join([
    ensure_python_interpreter('2.7.9'),
    ensure_python_interpreter('2.7.10'),
    ensure_python_interpreter('2.7.11'),
    ensure_python_interpreter('3.4.2'),
    ensure_python_interpreter('3.5.4'),
    ensure_python_interpreter('3.6.2'),
    ensure_python_interpreter('3.6.3')
  ])

  interpreters = find_compatible_interpreters(pex_python_path, ['>3'])
  assert interpreters[0].binary == pex_python_path.split(':')[3]  # 3.4.2

  interpreters = find_compatible_interpreters(pex_python_path, ['<3'])
  assert interpreters[0].binary == pex_python_path.split(':')[0]  # 2.7.9

  interpreters = find_compatible_interpreters(pex_python_path, ['>3.5.4'])
  assert interpreters[0].binary == pex_python_path.split(':')[5]  # 3.6.2

  interpreters = find_compatible_interpreters(pex_python_path, ['>3.4.2, <3.6'])
  assert interpreters[0].binary == pex_python_path.split(':')[4]  # 3.5.4

  interpreters = find_compatible_interpreters(pex_python_path, ['>3.6.2'])
  assert interpreters[0].binary == pex_python_path.split(':')[6]  # 3.6.3

  interpreters = find_compatible_interpreters(pex_python_path, ['<2'])
  assert not interpreters

  interpreters = find_compatible_interpreters(pex_python_path, ['>4'])
  assert not interpreters

  interpreters = find_compatible_interpreters(pex_python_path, ['<2.7.11, >2.7.9'])
  assert interpreters[0].binary == pex_python_path.split(':')[1]  # 2.7.10

  interpreters = find_compatible_interpreters('', ['<3'])
  assert interpreters[0] in PythonInterpreter.all()  # All interpreters on PATH
