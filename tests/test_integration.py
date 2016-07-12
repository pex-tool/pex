# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from textwrap import dedent

import pytest
from twitter.common.contextutil import environment_as, temporary_dir

from pex.compatibility import WINDOWS
from pex.installer import EggInstaller
from pex.testing import run_pex_command, run_simple_pex, run_simple_pex_test, temporary_content
from pex.util import DistributionHelper, named_temporary_file


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


def test_cache_disable():
  with temporary_dir() as tmp_home:
    with environment_as(HOME=tmp_home):
      with temporary_dir() as td:
        with temporary_dir() as output_dir:
          env = os.environ.copy()
          env['PEX_INTERPRETER'] = '1'

          output_path = os.path.join(output_dir, 'pex.pex')
          args = [
            'pex',
            '-o', output_path,
            '--not-zip-safe',
            '--disable-cache',
            '--pex-root={0}'.format(td),
          ]
          results = run_pex_command(args=args, env=env)
          results.assert_success()
          assert ['pex.pex'] == os.listdir(output_dir), 'Expected built pex file.'
          assert [] == os.listdir(tmp_home), 'Expected empty temp home dir.'


def test_pex_interpreter():
  with named_temporary_file() as fp:
    fp.write(b"print('Hello world')")
    fp.flush()

    env = os.environ.copy()
    env['PEX_INTERPRETER'] = '1'

    so, rc = run_simple_pex_test("", args=(fp.name,), coverage=True, env=env)
    assert so == b'Hello world\n'
    assert rc == 0


def test_pex_repl_cli():
  """Tests the REPL in the context of the pex cli itself."""
  stdin_payload = b'import sys; sys.exit(3)'

  with temporary_dir() as output_dir:
    # Create a temporary pex containing just `requests` with no entrypoint.
    pex_path = os.path.join(output_dir, 'pex.pex')
    results = run_pex_command(['--disable-cache',
                               'wheel',
                               'requests',
                               './',
                               '-e', 'pex.bin.pex:main',
                               '-o', pex_path])
    results.assert_success()

    # Test that the REPL is functional.
    stdout, rc = run_simple_pex(pex_path, stdin=stdin_payload)
    assert rc == 3
    assert b'>>>' in stdout


def test_pex_repl_built():
  """Tests the REPL in the context of a built pex."""
  stdin_payload = b'import requests; import sys; sys.exit(3)'

  with temporary_dir() as output_dir:
    # Create a temporary pex containing just `requests` with no entrypoint.
    pex_path = os.path.join(output_dir, 'requests.pex')
    results = run_pex_command(['--disable-cache', 'requests', '-o', pex_path])
    results.assert_success()

    # Test that the REPL is functional.
    stdout, rc = run_simple_pex(pex_path, stdin=stdin_payload)
    assert rc == 3
    assert b'>>>' in stdout


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


def test_entry_point_exit_code():
  setup_py = dedent("""
    from setuptools import setup

    setup(
      name='my_app',
      version='0.0.0',
      zip_safe=True,
      packages=[''],
      entry_points={'console_scripts': ['my_app = my_app:do_something']},
    )
  """)

  error_msg = 'setuptools expects this to exit non-zero'

  my_app = dedent("""
    def do_something():
      return '%s'
  """ % error_msg)

  with temporary_content({'setup.py': setup_py, 'my_app.py': my_app}) as project_dir:
    installer = EggInstaller(project_dir)
    dist = DistributionHelper.distribution_from_path(installer.bdist())
    so, rc = run_simple_pex_test('', env={'PEX_SCRIPT': 'my_app'}, dists=[dist])
    assert so.decode('utf-8').strip() == error_msg
    assert rc == 1
