# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

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


def test_find_compatible_interpreter_in_python_path():
  root_dir = os.getcwd()
  interpreters = [PythonInterpreter.from_binary(root_dir + '/.tox/py27/bin/python2.7'),
                  PythonInterpreter.from_binary(root_dir + '/.tox/py36/bin/python3.6')]
  pi2 = list(filter(lambda x: '2' in x.binary, interpreters))
  pi3 = list(filter(lambda x: '3' in x.binary, interpreters))
  # for some reason pi2 from binary chops off 2.7 from the binary name so I add here
  pex_python_path = ':'.join([pi2[0].binary + '2.7'] + [pi3[0].binary])

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '<3')
  assert interpreter.binary == pi2[0].binary

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '>3')
  assert interpreter.binary == pi3[0].binary

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '<2')
  assert interpreter is None

  interpreter = _find_compatible_interpreter_in_pex_python_path(pex_python_path, '>4')
  assert interpreter is None
