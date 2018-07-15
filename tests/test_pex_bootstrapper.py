# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from twitter.common.contextutil import temporary_dir

from pex.common import open_zip
from pex.interpreter import PythonInterpreter
from pex.pex_bootstrapper import find_compatible_interpreters, get_pex_info
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


def assert_interpreters(interpreters, *expected):
  assert list(expected) == [pi.binary for pi in interpreters]


def test_find_compatible_interpreters():
  pi_2_7_10 = ensure_python_interpreter('2.7.10')
  pi_3_6_2 = ensure_python_interpreter('3.6.2')
  pi_3_6_3 = ensure_python_interpreter('3.6.3')
  pex_python_path = ':'.join([
    pi_2_7_10,
    pi_3_6_2,
    pi_3_6_3
  ])

  interpreters = find_compatible_interpreters(pex_python_path, [])
  assert_interpreters(interpreters, pi_2_7_10, pi_3_6_2, pi_3_6_3)

  interpreters = find_compatible_interpreters(pex_python_path, ['>3'])
  assert_interpreters(interpreters, pi_3_6_2, pi_3_6_3)

  interpreters = find_compatible_interpreters(pex_python_path, ['<3'])
  assert_interpreters(interpreters, pi_2_7_10)

  interpreters = find_compatible_interpreters(pex_python_path, ['<=2.7.10'])
  assert_interpreters(interpreters, pi_2_7_10)

  interpreters = find_compatible_interpreters(pex_python_path, ['>=3.6.2'])
  assert_interpreters(interpreters, pi_3_6_2, pi_3_6_3)

  interpreters = find_compatible_interpreters(pex_python_path, ['>2.7.10, <3.6.3'])
  assert_interpreters(interpreters, pi_3_6_2)

  interpreters = find_compatible_interpreters(pex_python_path, ['>2, <=3'])
  assert_interpreters(interpreters, pi_2_7_10)

  interpreters = find_compatible_interpreters(pex_python_path, ['>=2.7, <3'])
  assert_interpreters(interpreters, pi_2_7_10)

  interpreters = find_compatible_interpreters(pex_python_path, ['>3.6.2'])
  assert_interpreters(interpreters, pi_3_6_3)

  interpreters = find_compatible_interpreters(pex_python_path, ['<2'])
  assert not interpreters

  interpreters = find_compatible_interpreters(pex_python_path, ['>4'])
  assert not interpreters

  interpreters = find_compatible_interpreters('', ['<3'])
  assert set(interpreters).issubset(set(PythonInterpreter.all()))  # All interpreters on PATH


def test_find_compatible_interpreters_directories_ignored():
  pi_2_7_10 = ensure_python_interpreter('2.7.10')
  pi_3_6_3 = ensure_python_interpreter('3.6.3')
  pex_python_path = ':'.join([
    os.path.dirname(pi_2_7_10),
    pi_3_6_3
  ])

  interpreters = find_compatible_interpreters(pex_python_path, ['>2'])
  assert_interpreters(interpreters, pi_3_6_3)

  interpreters = find_compatible_interpreters(pex_python_path, [])
  assert_interpreters(interpreters, pi_3_6_3)

  interpreters = find_compatible_interpreters(pex_python_path, ['<2'])
  assert not interpreters
