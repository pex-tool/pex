# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import pytest

from pex.interpreter import PythonInterpreter
from pex.pex_bootstrapper import find_compatible_interpreters, _bootstrap
from pex.testing import IS_PYPY, PY27, PY35, PY36, ensure_python_interpreter

EMPTY_FIXTURE_PEX = os.path.join(os.path.dirname(__file__), 'empty_test_fixture.pex')


@pytest.mark.skipif(IS_PYPY)
def test_find_compatible_interpreters():
  py27 = ensure_python_interpreter(PY27)
  py35 = ensure_python_interpreter(PY35)
  py36 = ensure_python_interpreter(PY36)
  pex_python_path = ':'.join([py27, py35, py36])

  def find_interpreters(*constraints):
    return [interp.binary for interp in
            find_compatible_interpreters(path=pex_python_path,
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


def test_bootstrap():
  """Simple test against an empty .pex file"""
  pex_info = _bootstrap(EMPTY_FIXTURE_PEX)
  # code_hash is arbitrary; it's just what was written into the test fixture.
  # It is only here to ensure that we're actually reading the file, and not
  # returning a defaults-only PexInfo.
  assert pex_info.code_hash == 'da39a3ee5e6b4b0d3255bfef95601890afd80709'
  assert pex_info.requirements == []
  assert pex_info.zip_safe is True


def test_bootstrap_with_vars_dict():
  """Test that extra_vars passed in as a dict are considered"""
  extra_vars = {
    "pex_root": "some_dir",
    "script": "my_dict_test_script"
  }
  pex_info = _bootstrap(EMPTY_FIXTURE_PEX, include_pexrc=False, extra_vars=extra_vars)
  assert pex_info.pex_root == "some_dir"
  assert pex_info.script == "my_dict_test_script"


def test_bootstrap_with_vars_json():
  """Test that extra_vars passed in as a JSON string are considered"""
  extra_vars = {
    "pex_root": "some_dir",
    "script": "my_json_test_script"
  }
  json_vars = json.dumps(extra_vars)
  pex_info = _bootstrap(EMPTY_FIXTURE_PEX, include_pexrc=False, extra_vars=json_vars)
  assert pex_info.pex_root == "some_dir"
  assert pex_info.script == "my_json_test_script"


def test_bootstrap_with_pexrc():
  """Test that pexrc files are considered"""
  pass


def test_bootstrap_with_pexrc_and_vars():
  """Test that both pexrc files and passed-in extra_vars are considered in a suitable order"""
  pass
