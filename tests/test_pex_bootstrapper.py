# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.interpreter import PythonInterpreter
from pex.pex_bootstrapper import find_compatible_interpreters
from pex.testing import IS_PYPY, PY27, PY35, PY36, ensure_python_interpreter


@pytest.mark.skipif(IS_PYPY)
def test_find_compatible_interpreters():
  py27 = ensure_python_interpreter(PY27)
  py35 = ensure_python_interpreter(PY35)
  py36 = ensure_python_interpreter(PY36)
  pex_python_path = ':'.join([py27, py35, py36])

  def find_interpreters(*constraints):
    return [interp.binary for interp in
            find_compatible_interpreters(pex_python_path=pex_python_path,
                                         compatibility_constraints=constraints)]

  assert [py35, py36] == find_interpreters('>3')
  assert [py27] == find_interpreters('<3')

  assert [py36] == find_interpreters('>{}'.format(PY35))
  assert [py35] == find_interpreters('>{}, <{}'.format(PY27, PY36))
  assert [py36] == find_interpreters('>=3.6')

  assert [] == find_interpreters('<2')
  assert [] == find_interpreters('>4')
  assert [] == find_interpreters('>{}, <{}'.format(PY27, PY35))

  # All interpreters on PATH including whatever interpreter is currently running.
  all_known_interpreters = set(PythonInterpreter.all())
  all_known_interpreters.add(PythonInterpreter.get())

  interpreters = find_compatible_interpreters(compatibility_constraints=['<3'])
  assert set(interpreters).issubset(all_known_interpreters)
