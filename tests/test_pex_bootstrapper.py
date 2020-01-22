# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from textwrap import dedent

from pex.interpreter import PythonInterpreter
from pex.pex_bootstrapper import iter_compatible_interpreters
from pex.testing import PY27, PY35, PY36, ensure_python_interpreter


def find_interpreters(path, *constraints):
  return [interp.binary for interp in
          iter_compatible_interpreters(path=os.pathsep.join(path),
                                       compatibility_constraints=constraints)]


def test_find_compatible_interpreters():
  py27 = ensure_python_interpreter(PY27)
  py35 = ensure_python_interpreter(PY35)
  py36 = ensure_python_interpreter(PY36)
  path = [py27, py35, py36]

  assert [py35, py36] == find_interpreters(path, '>3')
  assert [py27] == find_interpreters(path, '<3')

  assert [py36] == find_interpreters(path, '>{}'.format(PY35))
  assert [py35] == find_interpreters(path, '>{}, <{}'.format(PY27, PY36))
  assert [py36] == find_interpreters(path, '>=3.6')

  assert [] == find_interpreters(path, '<2')
  assert [] == find_interpreters(path, '>4')
  assert [] == find_interpreters(path, '>{}, <{}'.format(PY27, PY35))

  # All interpreters on PATH including whatever interpreter is currently running.
  all_known_interpreters = set(PythonInterpreter.all())
  all_known_interpreters.add(PythonInterpreter.get())

  interpreters = set(iter_compatible_interpreters(compatibility_constraints=['<3']))
  i_rendered = '\n      '.join(sorted(map(repr, interpreters)))
  aki_rendered = '\n      '.join(sorted(map(repr, all_known_interpreters)))
  assert interpreters.issubset(all_known_interpreters), dedent(
    """
    interpreters '<3':
      {interpreters}

    all known interpreters:
      {all_known_interpreters}
    """.format(interpreters=i_rendered, all_known_interpreters=aki_rendered)
  )


def test_find_compatible_interpreters_bias_current():
  py36 = ensure_python_interpreter(PY36)
  assert [os.path.realpath(sys.executable), py36] == find_interpreters([py36, sys.executable])
  assert [os.path.realpath(sys.executable), py36] == find_interpreters([sys.executable, py36])
