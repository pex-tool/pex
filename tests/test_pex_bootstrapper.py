# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from twitter.common.contextutil import temporary_dir

from pex.common import open_zip
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


def test_find_compatible_interpreters():
  ensure_python_interpreter('2.7.10')
  ensure_python_interpreter('3.6.3')
  pex_python_path = ':'.join([os.getcwd() + '/.pyenv_test/versions/2.7.10/bin/python2.7',
                              os.getcwd() + '/.pyenv_test/versions/3.6.3/bin/python3.6'])

  interpreters = find_compatible_interpreters(pex_python_path, ['>3'])
  assert interpreters[0].binary == pex_python_path.split(':')[1]

  interpreters = find_compatible_interpreters(pex_python_path, ['<3'])
  assert interpreters[0].binary == pex_python_path.split(':')[0]

  interpreters = find_compatible_interpreters(pex_python_path, ['<2'])
  assert not interpreters

  interpreters = find_compatible_interpreters(pex_python_path, ['>4'])
  assert not interpreters
