# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import textwrap
from types import ModuleType

import pytest

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


def test_pex_sys_exit_does_not_raise():
  body = "import sys; sys.exit(2)"
  so, rc = run_simple_pex_test(body)
  assert so == b'', 'Should not print SystemExit exception.'
  assert rc == 2


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


@pytest.mark.parametrize('project_name', ('my_project', 'my-project'))
@pytest.mark.parametrize('installer_impl', (EggInstaller, WheelInstaller))
def test_pex_script(installer_impl, project_name):
  with make_installer(name=project_name, installer_impl=installer_impl) as installer:
    bdist = DistributionHelper.distribution_from_path(installer.bdist())

    env_copy = os.environ.copy()
    env_copy['PEX_SCRIPT'] = 'hello_world'
    so, rc = run_simple_pex_test('', env=env_copy)
    assert rc == 1, so.decode('utf-8')
    assert b'Could not find' in so

    so, rc = run_simple_pex_test('', env=env_copy, dists=[bdist])
    assert rc == 0, so.decode('utf-8')
    assert b'hello world' in so

    env_copy['PEX_SCRIPT'] = 'shell_script'
    so, rc = run_simple_pex_test('', env=env_copy, dists=[bdist])
    assert rc == 1, so.decode('utf-8')
    assert b'Unable to parse' in so
