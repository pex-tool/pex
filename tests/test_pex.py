# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
import textwrap

import pytest

from pex.testing import run_simple_pex_test


@pytest.mark.skipif('sys.version_info > (3,)')
def test_pex_uncaught_exceptions():
  body = "raise Exception('This is an exception')"
  so, rc = run_simple_pex_test(body)
  assert b'This is an exception' in so, 'Standard out was: %s' % so
  assert rc == 1


def test_pex_sys_exit_does_not_raise():
  body = "import sys; sys.exit(2)"
  so, rc = run_simple_pex_test(body)
  assert so == b'', 'Should not print SystemExit exception.'
  assert rc == 2


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
