# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

import pytest
from twitter.common.contextutil import environment_as, temporary_dir

from pex.compatibility import WINDOWS
from pex.testing import run_pex_command, run_simple_pex_test
from pex.util import named_temporary_file


def test_pex_execute():
  body = "print('Hello')"
  _, rc = run_simple_pex_test(body, coverage=True)
  assert rc == 0


def test_pex_raise():
  body = "raise Exception('This will improve coverage.')"
  run_simple_pex_test(body, coverage=True)


def test_pex_root():
  with temporary_dir() as tmp_home:
    with environment_as(HOME=tmp_home):
      with temporary_dir() as td:
        with temporary_dir() as output_dir:
          env = os.environ.copy()
          env['PEX_INTERPRETER'] = '1'

          output_path = os.path.join(output_dir, 'pex.pex')
          args = ['pex', '-o', output_path, '--not-zip-safe', '--pex-root={0}'.format(td)]
          results = run_pex_command(args=args, env=env)
          results.assert_success()
          assert ['pex.pex'] == os.listdir(output_dir), 'Expected built pex file.'
          assert [] == os.listdir(tmp_home), 'Expected empty temp home dir.'
          assert 'build' in os.listdir(td), 'Expected build directory in tmp pex root.'


def test_pex_interpreter():
  with named_temporary_file() as fp:
    fp.write(b"print('Hello world')")
    fp.flush()

    env = os.environ.copy()
    env['PEX_INTERPRETER'] = '1'

    so, rc = run_simple_pex_test("", args=(fp.name,), coverage=True, env=env)
    assert so == b'Hello world\n'
    assert rc == 0


@pytest.mark.skipif(WINDOWS, reason='No symlinks on windows')
def test_pex_python_symlink():
  with temporary_dir() as td:
    with environment_as(HOME=td):
      symlink_path = os.path.join(td, 'python-symlink')
      os.symlink(sys.executable, symlink_path)
      pexrc_path = os.path.join(td, '.pexrc')
      with open(pexrc_path, 'w') as pexrc:
        pexrc.write("PEX_PYTHON=%s" % symlink_path)

      body = "print('Hello')"
      _, rc = run_simple_pex_test(body, coverage=True)
      assert rc == 0
