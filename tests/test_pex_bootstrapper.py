# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex.common import open_zip
from pex.interpreter import PythonInterpreter
from pex.pex_bootstrapper import find_compatible_interpreters, get_pex_info
from pex.testing import (
    IS_PYPY,
    PY27,
    PY35,
    PY36,
    ensure_python_interpreter,
    temporary_dir,
    write_simple_pex
)


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
  py27 = ensure_python_interpreter(PY27)
  py35 = ensure_python_interpreter(PY35)
  py36 = ensure_python_interpreter(PY36)
  pex_python_path = ':'.join([py27, py35, py36])

  def find_interpreters(*constraints):
    return [interp.binary for interp in find_compatible_interpreters(pex_python_path, constraints)]

  assert [py35, py36] == find_interpreters('>3')
  assert [py27] == find_interpreters('<3')

  assert [py36] == find_interpreters('>{}'.format(PY35))
  assert [py35] == find_interpreters('>{}, <{}'.format(PY27, PY36))
  assert [py36] == find_interpreters('>=3.6')

  assert [] == find_interpreters('<2')
  assert [] == find_interpreters('>4')
  assert [] == find_interpreters('>{}, <{}'.format(PY27, PY35))

  # All interpreters on PATH.
  interpreters = find_compatible_interpreters(pex_python_path='', compatibility_constraints=['<3'])
  assert set(interpreters).issubset(set(PythonInterpreter.all()))
