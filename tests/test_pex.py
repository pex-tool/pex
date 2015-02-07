# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import textwrap
from types import ModuleType

import pytest

from pex.pex import PEX
from pex.testing import run_simple_pex_test


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
