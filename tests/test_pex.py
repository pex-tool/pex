# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import textwrap
from types import ModuleType

import pytest

from pex.compatibility import to_bytes
from pex.installer import EggInstaller, WheelInstaller
from pex.pex import PEX
from pex.testing import make_installer, run_simple_pex_test
from pex.util import DistributionHelper


@pytest.mark.skipif('sys.version_info > (3,)')
def test_pex_uncaught_exceptions():
  body = "raise Exception('This is an exception')"
  so, rc = run_simple_pex_test(body)
  assert b'This is an exception' in so, 'Standard out was: %s' % so
  assert rc == 1


def test_excepthook_honored():
  body = textwrap.dedent("""
  import sys

  def excepthook(ex_type, ex, tb):
    print('Custom hook called with: {0}'.format(ex))
    sys.exit(42)

  sys.excepthook = excepthook

  raise Exception('This is an exception')
  """)

  so, rc = run_simple_pex_test(body)
  assert so == b'Custom hook called with: This is an exception\n', 'Standard out was: %s' % so
  assert rc == 42


def _test_sys_exit(arg, expected_output, expected_rc):
  body = "import sys; sys.exit({arg})".format(arg=arg)
  so, rc = run_simple_pex_test(body)
  assert so == expected_output, 'Should not print SystemExit traceback.'
  assert rc == expected_rc


def test_pex_sys_exit_does_not_print_for_numeric_value():
  _test_sys_exit(2, b'', 2)


def test_pex_sys_exit_prints_non_numeric_value_no_traceback():
  text = 'something went wrong'

  sys_exit_arg = '"' + text + '"'
  # encode the string somehow that's compatible with 2 and 3
  expected_output = to_bytes(text) + b'\n'
  _test_sys_exit(sys_exit_arg, expected_output, 1)


def test_pex_sys_exit_doesnt_print_none():
  _test_sys_exit('', to_bytes(''), 0)


def test_pex_sys_exit_prints_objects():
  _test_sys_exit('Exception("derp")', to_bytes('derp\n'), 1)


@pytest.mark.skipif('hasattr(sys, "pypy_version_info")')
def test_pex_atexit_swallowing():
  body = textwrap.dedent("""
  import atexit

  def raise_on_exit():
    raise Exception('This is an exception')

  atexit.register(raise_on_exit)
  """)

  so, rc = run_simple_pex_test(body)
  assert so == b''
  assert rc == 0

  env_copy = os.environ.copy()
  env_copy.update(PEX_TEARDOWN_VERBOSE='1')
  so, rc = run_simple_pex_test(body, env=env_copy)
  assert b'This is an exception' in so
  assert rc == 0


def test_minimum_sys_modules():
  # builtins stay
  builtin_module = ModuleType('my_builtin')
  modules = {'my_builtin': builtin_module}
  new_modules = PEX.minimum_sys_modules([], modules)
  assert new_modules == modules
  new_modules = PEX.minimum_sys_modules(['bad_path'], modules)
  assert new_modules == modules

  # tainted evict
  tainted_module = ModuleType('tainted_module')
  tainted_module.__path__ = ['bad_path']
  modules = {'tainted_module': tainted_module}
  new_modules = PEX.minimum_sys_modules([], modules)
  assert new_modules == modules
  new_modules = PEX.minimum_sys_modules(['bad_path'], modules)
  assert new_modules == {}
  assert tainted_module.__path__ == []

  # tainted cleaned
  tainted_module = ModuleType('tainted_module')
  tainted_module.__path__ = ['bad_path', 'good_path']
  modules = {'tainted_module': tainted_module}
  new_modules = PEX.minimum_sys_modules([], modules)
  assert new_modules == modules
  new_modules = PEX.minimum_sys_modules(['bad_path'], modules)
  assert new_modules == modules
  assert tainted_module.__path__ == ['good_path']


@pytest.mark.parametrize('zip_safe', (False, True))
@pytest.mark.parametrize('project_name', ('my_project', 'my-project'))
@pytest.mark.parametrize('installer_impl', (EggInstaller, WheelInstaller))
def test_pex_script(installer_impl, project_name, zip_safe):
  kw = dict(name=project_name, installer_impl=installer_impl, zip_safe=zip_safe)
  with make_installer(**kw) as installer:
    bdist = DistributionHelper.distribution_from_path(installer.bdist())

    env_copy = os.environ.copy()
    env_copy['PEX_SCRIPT'] = 'hello_world'
    so, rc = run_simple_pex_test('', env=env_copy)
    assert rc == 1, so.decode('utf-8')
    assert b'Could not find script hello_world' in so

    so, rc = run_simple_pex_test('', env=env_copy, dists=[bdist])
    assert rc == 0, so.decode('utf-8')
    assert b'hello world' in so

    env_copy['PEX_SCRIPT'] = 'shell_script'
    so, rc = run_simple_pex_test('', env=env_copy, dists=[bdist])
    assert rc == 1, so.decode('utf-8')
    assert b'Unable to parse' in so
