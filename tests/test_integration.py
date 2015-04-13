# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from twitter.common.contextutil import temporary_file

from pex.testing import run_simple_pex_test


def test_pex_execute():
  body = "print('Hello')"
  _, rc = run_simple_pex_test(body, coverage=True)
  assert rc == 0


def test_pex_raise():
  body = "raise Exception('This will improve coverage.')"
  run_simple_pex_test(body, coverage=True)


def test_pex_interpreter():
  with temporary_file() as fp:
    fp.write(b"print('Hello world')")
    fp.flush()

    env = os.environ.copy()
    env['PEX_INTERPRETER'] = '1'

    so, rc = run_simple_pex_test("", args=(fp.name,), coverage=True, env=env)
    assert so == b'Hello world\n'
    assert rc == 0
