# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from textwrap import dedent

import pytest
from twitter.common.contextutil import environment_as, temporary_dir

from pex.compatibility import WINDOWS
from pex.installer import EggInstaller
from pex.pex_bootstrapper import get_pex_info
from pex.testing import (
    ensure_python_interpreter,
    get_dep_dist_names_from_pex,
    run_pex_command,
    run_simple_pex,
    run_simple_pex_test,
    temporary_content
)
from pex.util import DistributionHelper, named_temporary_file

NOT_CPYTHON_36 = (
  "hasattr(sys, 'pypy_version_info') or "
  "(sys.version_info[0], sys.version_info[1]) != (3, 6)"
)


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


@pytest.mark.skipif(NOT_CPYTHON_36)
def test_pex_multi_resolve():
  """Tests multi-interpreter + multi-platform resolution."""
  with temporary_dir() as output_dir:
    pex_path = os.path.join(output_dir, 'pex.pex')
    results = run_pex_command(['--disable-cache',
                               'lxml==3.8.0',
                               '--platform=manylinux1-x86_64',
                               '--platform=macosx-10.6-x86_64',
                               '--python=python2.7',
                               '--python=python3.6',
                               '-o', pex_path])
    results.assert_success()

    included_dists = get_dep_dist_names_from_pex(pex_path, 'lxml')
    assert len(included_dists) == 4
    for dist_substr in ('-cp27-', '-cp36-', '-manylinux1_x86_64', '-macosx_'):
      assert any(dist_substr in f for f in included_dists)


@pytest.mark.xfail(reason='See https://github.com/pantsbuild/pants/issues/4682')
def test_pex_re_exec_failure():
  with temporary_dir() as output_dir:

    # create 2 pex files for PEX_PATH
    pex1_path = os.path.join(output_dir, 'pex1.pex')
    res1 = run_pex_command(['--disable-cache', 'requests', '-o', pex1_path])
    res1.assert_success()
    pex2_path = os.path.join(output_dir, 'pex2.pex')
    res2 = run_pex_command(['--disable-cache', 'flask', '-o', pex2_path])
    res2.assert_success()
    pex_path = ':'.join(os.path.join(output_dir, name) for name in ('pex1.pex', 'pex2.pex'))

    # create test file test.py that attmepts to import modules from pex1/pex2
    test_file_path = os.path.join(output_dir, 'test.py')
    with open(test_file_path, 'w') as fh:
      fh.write(dedent('''
        import requests
        import flask
        import sys
        import os
        import subprocess
        if 'RAN_ONCE' in os.environ::
          print('Hello world')
        else:
          env = os.environ.copy()
          env['RAN_ONCE'] = '1'
          subprocess.call([sys.executable] + sys.argv, env=env)
          sys.exit()
        '''))

    # set up env for pex build with PEX_PATH in the environment
    env = os.environ.copy()
    env['PEX_PATH'] = pex_path

    # build composite pex of pex1/pex1
    pex_out_path = os.path.join(output_dir, 'out.pex')
    run_pex_command(['--disable-cache',
      'wheel',
      '-o', pex_out_path])

    # run test.py with composite env
    stdout, rc = run_simple_pex(pex_out_path, [test_file_path], env=env)

    assert rc == 0
    assert stdout == b'Hello world\n'


def test_pex_path_arg():
  with temporary_dir() as output_dir:

    # create 2 pex files for PEX_PATH
    pex1_path = os.path.join(output_dir, 'pex1.pex')
    res1 = run_pex_command(['--disable-cache', 'requests', '-o', pex1_path])
    res1.assert_success()
    pex2_path = os.path.join(output_dir, 'pex2.pex')
    res2 = run_pex_command(['--disable-cache', 'flask', '-o', pex2_path])
    res2.assert_success()
    pex_path = ':'.join(os.path.join(output_dir, name) for name in ('pex1.pex', 'pex2.pex'))

    # parameterize the pex arg for test.py
    pex_out_path = os.path.join(output_dir, 'out.pex')
    # create test file test.py that attempts to import modules from pex1/pex2
    test_file_path = os.path.join(output_dir, 'test.py')
    with open(test_file_path, 'w') as fh:
      fh.write(dedent('''
        import requests
        import flask
        import sys
        import os
        import subprocess
        if 'RAN_ONCE' in os.environ:
          print('Success!')
        else:
          env = os.environ.copy()
          env['RAN_ONCE'] = '1'
          subprocess.call([sys.executable] + ['%s'] + sys.argv, env=env)
          sys.exit()
        ''' % pex_out_path))

    # build out.pex composed from pex1/pex1
    run_pex_command(['--disable-cache',
      '--pex-path={}'.format(pex_path),
      'wheel',
      '-o', pex_out_path])

    # run test.py with composite env
    stdout, rc = run_simple_pex(pex_out_path, [test_file_path])
    assert rc == 0
    assert stdout == b'Success!\n'


def test_pex_path_in_pex_info_and_env():
  with temporary_dir() as output_dir:

    # create 2 pex files for PEX-INFO pex_path
    pex1_path = os.path.join(output_dir, 'pex1.pex')
    res1 = run_pex_command(['--disable-cache', 'requests', '-o', pex1_path])
    res1.assert_success()
    pex2_path = os.path.join(output_dir, 'pex2.pex')
    res2 = run_pex_command(['--disable-cache', 'flask', '-o', pex2_path])
    res2.assert_success()
    pex_path = ':'.join(os.path.join(output_dir, name) for name in ('pex1.pex', 'pex2.pex'))

    # create a pex for environment PEX_PATH
    pex3_path = os.path.join(output_dir, 'pex3.pex')
    res3 = run_pex_command(['--disable-cache', 'wheel', '-o', pex3_path])
    res3.assert_success()
    env_pex_path = os.path.join(output_dir, 'pex3.pex')

    # parameterize the pex arg for test.py
    pex_out_path = os.path.join(output_dir, 'out.pex')
    # create test file test.py that attempts to import modules from pex1/pex2
    test_file_path = os.path.join(output_dir, 'test.py')
    with open(test_file_path, 'w') as fh:
      fh.write(dedent('''
        import requests
        import flask
        import wheel
        import sys
        import os
        import subprocess
        print('Success!')
        '''))

    # build out.pex composed from pex1/pex1
    run_pex_command(['--disable-cache',
      '--pex-path={}'.format(pex_path),
      '-o', pex_out_path])

    # load secondary PEX_PATH
    env = os.environ.copy()
    env['PEX_PATH'] = env_pex_path

    # run test.py with composite env
    stdout, rc = run_simple_pex(pex_out_path, [test_file_path], env=env)
    assert rc == 0
    assert stdout == b'Success!\n'


def test_interpreter_constraints_to_pex_info():
  with temporary_dir() as output_dir:
    # target python 2
    pex_out_path = os.path.join(output_dir, 'pex1.pex')
    res = run_pex_command(['--disable-cache',
      '--interpreter-constraint=>=2.7',
      '--interpreter-constraint=<3',
      '-o', pex_out_path])
    res.assert_success()
    pex_info = get_pex_info(pex_out_path)
    assert set(['>=2.7', '<3']) == set(pex_info.interpreter_constraints)

    # target python 3
    pex_out_path = os.path.join(output_dir, 'pex1.pex')
    res = run_pex_command(['--disable-cache',
      '--interpreter-constraint=>3',
      '-o', pex_out_path])
    res.assert_success()
    pex_info = get_pex_info(pex_out_path)
    assert ['>3'] == pex_info.interpreter_constraints


def test_interpreter_resolution_with_constraint_option():
  with temporary_dir() as output_dir:
    pex_out_path = os.path.join(output_dir, 'pex1.pex')
    res = run_pex_command(['--disable-cache',
      '--interpreter-constraint=>=2.7',
      '--interpreter-constraint=<3',
      '-o', pex_out_path])
    res.assert_success()
    pex_info = get_pex_info(pex_out_path)
    assert set(['>=2.7', '<3']) == set(pex_info.interpreter_constraints)
    assert pex_info.build_properties['version'][0] < 3


def test_interpreter_resolution_with_pex_python_path():
  with temporary_dir() as td:
    pexrc_path = os.path.join(td, '.pexrc')
    with open(pexrc_path, 'w') as pexrc:
      # set pex python path
      pex_python_path = ':'.join([
        ensure_python_interpreter('2.7.10'),
        ensure_python_interpreter('3.6.3')
      ])
      pexrc.write("PEX_PYTHON_PATH=%s" % pex_python_path)

    # constraints to build pex cleanly; PPP + pex_bootstrapper.py
    # will use these constraints to override sys.executable on pex re-exec
    interpreter_constraint1 = '>3' if sys.version_info[0] == 3 else '<3'
    interpreter_constraint2 = '<3.8' if sys.version_info[0] == 3 else '>=2.7'

    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
      '--rcfile=%s' % pexrc_path,
      '--interpreter-constraint=%s' % interpreter_constraint1,
      '--interpreter-constraint=%s' % interpreter_constraint2,
      '-o', pex_out_path])
    res.assert_success()

    stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
    stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)

    assert rc == 0
    if sys.version_info[0] == 3:
      assert str(pex_python_path.split(':')[1]).encode() in stdout
    else:
      assert str(pex_python_path.split(':')[0]).encode() in stdout


@pytest.mark.skipif(NOT_CPYTHON_36)
def test_interpreter_resolution_pex_python_path_precedence_over_pex_python():
  with temporary_dir() as td:
    pexrc_path = os.path.join(td, '.pexrc')
    with open(pexrc_path, 'w') as pexrc:
      # set both PPP and PP
      pex_python_path = ':'.join([
        ensure_python_interpreter('2.7.10'),
        ensure_python_interpreter('3.6.3')
      ])
      pexrc.write("PEX_PYTHON_PATH=%s\n" % pex_python_path)
      pex_python = '/path/to/some/python'
      pexrc.write("PEX_PYTHON=%s" % pex_python)

    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
      '--rcfile=%s' % pexrc_path,
      '--interpreter-constraint=>3',
      '--interpreter-constraint=<3.8',
      '-o', pex_out_path])
    res.assert_success()

    stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
    stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
    assert rc == 0
    correct_interpreter_path = pex_python_path.split(':')[1].encode()
    assert correct_interpreter_path in stdout


def test_plain_pex_exec_no_ppp_no_pp_no_constraints():
  with temporary_dir() as td:
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
      '-o', pex_out_path])
    res.assert_success()

    stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
    stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
    assert rc == 0
    assert str(sys.executable).encode() in stdout


def test_pex_exec_with_pex_python_path_only():
  with temporary_dir() as td:
    pexrc_path = os.path.join(td, '.pexrc')
    with open(pexrc_path, 'w') as pexrc:
      # set pex python path
      pex_python_path = ':'.join([
        ensure_python_interpreter('2.7.10'),
        ensure_python_interpreter('3.6.3')
      ])
      pexrc.write("PEX_PYTHON_PATH=%s" % pex_python_path)

    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
      '--rcfile=%s' % pexrc_path,
      '-o', pex_out_path])
    res.assert_success()

    # test that pex bootstrapper selects lowest version interpreter
    # in pex python path (python2.7)
    stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
    stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
    assert rc == 0
    assert str(pex_python_path.split(':')[0]).encode() in stdout


def test_pex_exec_with_pex_python_path_and_pex_python_but_no_constraints():
  with temporary_dir() as td:
    pexrc_path = os.path.join(td, '.pexrc')
    with open(pexrc_path, 'w') as pexrc:
      # set both PPP and PP
      pex_python_path = ':'.join([
        ensure_python_interpreter('2.7.10'),
        ensure_python_interpreter('3.6.3')
      ])
      pexrc.write("PEX_PYTHON_PATH=%s\n" % pex_python_path)
      pex_python = '/path/to/some/python'
      pexrc.write("PEX_PYTHON=%s" % pex_python)

    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
      '--rcfile=%s' % pexrc_path,
      '-o', pex_out_path])
    res.assert_success()

    # test that pex bootstrapper selects lowest version interpreter
    # in pex python path (python2.7)
    stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
    stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
    assert rc == 0
    assert str(pex_python_path.split(':')[0]).encode() in stdout


def test_pex_python():
  with temporary_dir() as td:
    pexrc_path = os.path.join(td, '.pexrc')
    with open(pexrc_path, 'w') as pexrc:
      pex_python = ensure_python_interpreter('3.6.3')
      pexrc.write("PEX_PYTHON=%s" % pex_python)

    # test PEX_PYTHON with valid constraints
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
      '--rcfile=%s' % pexrc_path,
      '--interpreter-constraint=>3',
      '--interpreter-constraint=<3.8',
      '-o', pex_out_path])
    res.assert_success()

    stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
    stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
    assert rc == 0
    correct_interpreter_path = pex_python.encode()
    assert correct_interpreter_path in stdout

    # test PEX_PYTHON with incompatible constraints
    pexrc_path = os.path.join(td, '.pexrc')
    with open(pexrc_path, 'w') as pexrc:
      pex_python = ensure_python_interpreter('2.7.10')
      pexrc.write("PEX_PYTHON=%s" % pex_python)

    pex_out_path = os.path.join(td, 'pex2.pex')
    res = run_pex_command(['--disable-cache',
      '--rcfile=%s' % pexrc_path,
      '--interpreter-constraint=>3',
      '--interpreter-constraint=<3.8',
      '-o', pex_out_path])
    res.assert_success()

    stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
    stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
    assert rc == 1
    fail_str = 'not compatible with specified interpreter constraints'.encode()
    assert fail_str in stdout

    # test PEX_PYTHON with no constraints
    pex_out_path = os.path.join(td, 'pex3.pex')
    res = run_pex_command(['--disable-cache',
      '--rcfile=%s' % pexrc_path,
      '-o', pex_out_path])
    res.assert_success()

    stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
    stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
    assert rc == 0
    correct_interpreter_path = pex_python.encode()
    assert correct_interpreter_path in stdout


def test_entry_point_targeting():
  """Test bugfix for https://github.com/pantsbuild/pex/issues/434"""
  with temporary_dir() as td:
    pexrc_path = os.path.join(td, '.pexrc')
    with open(pexrc_path, 'w') as pexrc:
      pex_python = ensure_python_interpreter('3.6.3')
      pexrc.write("PEX_PYTHON=%s" % pex_python)

    # test pex with entry point
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
      'autopep8',
      '-e', 'autopep8',
      '-o', pex_out_path])
    res.assert_success()

    stdout, rc = run_simple_pex(pex_out_path)
    assert 'usage: autopep8'.encode() in stdout
