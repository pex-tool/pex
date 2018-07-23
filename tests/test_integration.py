# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
import platform
import subprocess
import sys
from contextlib import contextmanager
from textwrap import dedent

import pytest
from twitter.common.contextutil import environment_as, temporary_dir

from pex.compatibility import WINDOWS
from pex.installer import EggInstaller
from pex.pex_bootstrapper import get_pex_info
from pex.testing import (
    IS_PYPY,
    NOT_CPYTHON27,
    NOT_CPYTHON27_OR_LINUX,
    NOT_CPYTHON27_OR_OSX,
    NOT_CPYTHON36,
    NOT_CPYTHON36_OR_LINUX,
    ensure_python_interpreter,
    get_dep_dist_names_from_pex,
    run_pex_command,
    run_simple_pex,
    run_simple_pex_test,
    temporary_content
)
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


# TODO: https://github.com/pantsbuild/pex/issues/479
@pytest.mark.skipif(NOT_CPYTHON36_OR_LINUX,
                    reason='inherits linux abi on linux w/ no backing packages')
def test_pex_multi_resolve():
  """Tests multi-interpreter + multi-platform resolution."""
  with temporary_dir() as output_dir:
    pex_path = os.path.join(output_dir, 'pex.pex')
    results = run_pex_command(['--disable-cache',
                               'lxml==3.8.0',
                               '--no-build',
                               '--platform=linux-x86_64',
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


def test_interpreter_constraints_to_pex_info_py2():
  with temporary_dir() as output_dir:
    # target python 2
    pex_out_path = os.path.join(output_dir, 'pex_py2.pex')
    res = run_pex_command(['--disable-cache',
      '--interpreter-constraint=>=2.7',
      '--interpreter-constraint=<3',
      '-o', pex_out_path])
    res.assert_success()
    pex_info = get_pex_info(pex_out_path)
    assert set(['>=2.7', '<3']) == set(pex_info.interpreter_constraints)


@pytest.mark.skipif(IS_PYPY)
def test_interpreter_constraints_to_pex_info_py3():
  py3_interpreter = ensure_python_interpreter('3.6.3')
  with environment_as(PATH=os.path.dirname(py3_interpreter)):
    with temporary_dir() as output_dir:
      # target python 3
      pex_out_path = os.path.join(output_dir, 'pex_py3.pex')
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


@pytest.mark.skipif(IS_PYPY)
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


@pytest.mark.skipif(NOT_CPYTHON36)
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


@pytest.mark.skipif(IS_PYPY)
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


@pytest.mark.skipif(IS_PYPY)
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


@pytest.mark.skipif(IS_PYPY)
def test_pex_python():
  py2_path_interpreter = ensure_python_interpreter('2.7.10')
  py3_path_interpreter = ensure_python_interpreter('3.6.3')
  path = ':'.join([os.path.dirname(py2_path_interpreter), os.path.dirname(py3_path_interpreter)])
  with environment_as(PATH=path):
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


@pytest.mark.skipif(IS_PYPY)
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


@pytest.mark.skipif(IS_PYPY)
def test_interpreter_selection_using_os_environ_for_bootstrap_reexec():
  """
  This is a test for verifying the proper function of the
  pex bootstrapper's interpreter selection logic and validate a corresponding
  bugfix. More details on the nature of the bug can be found at:
  https://github.com/pantsbuild/pex/pull/441
  """
  with temporary_dir() as td:
    pexrc_path = os.path.join(td, '.pexrc')

    # Select pexrc interpreter versions based on test environemnt.
    # The parent interpreter is the interpreter we expect the parent pex to
    # execute with. The child interpreter is the interpreter we expect the
    # child pex to execute with.
    if (sys.version_info[0], sys.version_info[1]) == (3, 6):
      child_pex_interpreter_version = '3.6.3'
    else:
      child_pex_interpreter_version = '2.7.10'

    # Write parent pex's pexrc.
    with open(pexrc_path, 'w') as pexrc:
      pexrc.write("PEX_PYTHON=%s" % sys.executable)

    test_setup_path = os.path.join(td, 'setup.py')
    with open(test_setup_path, 'w') as fh:
      fh.write(dedent('''
        from setuptools import setup

        setup(
          name='tester',
          version='1.0',
          description='tests',
          author='tester',
          author_email='test@test.com',
          packages=['testing']
        )
        '''))

    os.mkdir(os.path.join(td, 'testing'))
    test_init_path = os.path.join(td, 'testing/__init__.py')
    with open(test_init_path, 'w') as fh:
      fh.write(dedent('''
        def tester():
          from pex.testing import (
            run_pex_command,
            run_simple_pex
          )
          import os
          import tempfile
          import shutil
          from textwrap import dedent
          td = tempfile.mkdtemp()
          try:
            pexrc_path = os.path.join(td, '.pexrc')
            with open(pexrc_path, 'w') as pexrc:
              pexrc.write("PEX_PYTHON={}")
            test_file_path = os.path.join(td, 'build_and_run_child_pex.py')
            with open(test_file_path, 'w') as fh:
              fh.write(dedent("""
                import sys
                print(sys.executable)
                """))
            pex_out_path = os.path.join(td, 'child.pex')
            res = run_pex_command(['--disable-cache',
              '-o', pex_out_path])
            stdin_payload = b'import sys; print(sys.executable); sys.exit(0)'
            stdout, rc = run_simple_pex(pex_out_path, stdin=stdin_payload)
            print(stdout)
          finally:
            shutil.rmtree(td)
        '''.format(ensure_python_interpreter(child_pex_interpreter_version))))

    pex_out_path = os.path.join(td, 'parent.pex')
    res = run_pex_command(['--disable-cache',
      'pex',
      '{}'.format(td),
      '-e', 'testing:tester',
      '-o', pex_out_path])
    res.assert_success()

    stdout, rc = run_simple_pex(pex_out_path)
    assert rc == 0
    # Ensure that child pex used the proper interpreter as specified by its pexrc.
    correct_interpreter_path = ensure_python_interpreter(child_pex_interpreter_version)
    correct_interpreter_path = correct_interpreter_path.encode()  # Py 2/3 compatibility
    assert correct_interpreter_path in stdout


def test_inherit_path_fallback():
  inherit_path("=fallback")


def test_inherit_path_backwards_compatibility():
  inherit_path("")


def test_inherit_path_prefer():
  inherit_path("=prefer")


def inherit_path(inherit_path):
  with temporary_dir() as output_dir:
    exe = os.path.join(output_dir, 'exe.py')
    body = "import sys ; print('\\n'.join(sys.path))"
    with open(exe, 'w') as f:
      f.write(body)

    pex_path = os.path.join(output_dir, 'pex.pex')
    results = run_pex_command([
      '--disable-cache',
      'msgpack_python',
      '--inherit-path{}'.format(inherit_path),
      '-o',
      pex_path,
    ])

    results.assert_success()

    env = os.environ.copy()
    env["PYTHONPATH"] = "/doesnotexist"
    stdout, rc = run_simple_pex(
      pex_path,
      args=(exe,),
      env=env,
    )
    assert rc == 0

    stdout_lines = stdout.decode().split('\n')
    requests_paths = tuple(i for i, l in enumerate(stdout_lines) if 'msgpack_python' in l)
    sys_paths = tuple(i for i, l in enumerate(stdout_lines) if 'doesnotexist' in l)
    assert len(requests_paths) == 1
    assert len(sys_paths) == 1

    if inherit_path == "=fallback":
      assert requests_paths[0] < sys_paths[0]
    else:
      assert requests_paths[0] > sys_paths[0]


def test_pex_multi_resolve_2():
  """Tests multi-interpreter + multi-platform resolution using extended platform notation."""
  with temporary_dir() as output_dir:
    pex_path = os.path.join(output_dir, 'pex.pex')
    results = run_pex_command(['--disable-cache',
                               'lxml==3.8.0',
                               '--no-build',
                               '--platform=linux-x86_64-cp-36-m',
                               '--platform=linux-x86_64-cp-27-m',
                               '--platform=macosx-10.6-x86_64-cp-36-m',
                               '--platform=macosx-10.6-x86_64-cp-27-m',
                               '-o', pex_path])
    results.assert_success()

    included_dists = get_dep_dist_names_from_pex(pex_path, 'lxml')
    assert len(included_dists) == 4
    for dist_substr in ('-cp27-', '-cp36-', '-manylinux1_x86_64', '-macosx_'):
      assert any(dist_substr in f for f in included_dists), (
        '{} was not found in wheel'.format(dist_substr)
      )


@contextmanager
def pex_manylinux_and_tag_selection_context():
  with temporary_dir() as output_dir:
    def do_resolve(req_name, req_version, platform, extra_flags=None):
      extra_flags = extra_flags or ''
      pex_path = os.path.join(output_dir, 'test.pex')
      results = run_pex_command(['--disable-cache',
                                 '--no-build',
                                 '%s==%s' % (req_name, req_version),
                                 '--platform=%s' % (platform),
                                 '-o', pex_path] + extra_flags.split())
      return pex_path, results

    def test_resolve(req_name, req_version, platform, substr, extra_flags=None):
      pex_path, results = do_resolve(req_name, req_version, platform, extra_flags)
      results.assert_success()
      included_dists = get_dep_dist_names_from_pex(pex_path, req_name.replace('-', '_'))
      assert any(
        substr in d for d in included_dists
      ), 'couldnt find {} in {}'.format(substr, included_dists)

    def ensure_failure(req_name, req_version, platform, extra_flags):
      pex_path, results = do_resolve(req_name, req_version, platform, extra_flags)
      results.assert_failure()

    yield test_resolve, ensure_failure


@pytest.mark.skipif(IS_PYPY)
def test_pex_manylinux_and_tag_selection_linux_msgpack():
  """Tests resolver manylinux support and tag targeting."""
  with pex_manylinux_and_tag_selection_context() as (test_resolve, ensure_failure):
    msgpack, msgpack_ver = 'msgpack-python', '0.4.7'
    test_msgpack = functools.partial(test_resolve, msgpack, msgpack_ver)

    # Exclude 3.3 and 3.6 because no 33/36 wheel exists on pypi.
    if (sys.version_info[0], sys.version_info[1]) not in [(3, 3), (3, 6)]:
      test_msgpack('linux-x86_64', 'manylinux1_x86_64.whl')

    test_msgpack('linux-x86_64-cp-27-m', 'msgpack_python-0.4.7-cp27-cp27m-manylinux1_x86_64.whl')
    test_msgpack('linux-x86_64-cp-27-mu', 'msgpack_python-0.4.7-cp27-cp27mu-manylinux1_x86_64.whl')
    test_msgpack('linux-i686-cp-27-m', 'msgpack_python-0.4.7-cp27-cp27m-manylinux1_i686.whl')
    test_msgpack('linux-i686-cp-27-mu', 'msgpack_python-0.4.7-cp27-cp27mu-manylinux1_i686.whl')
    test_msgpack('linux-x86_64-cp-27-mu', 'msgpack_python-0.4.7-cp27-cp27mu-manylinux1_x86_64.whl')
    test_msgpack('linux-x86_64-cp-34-m', 'msgpack_python-0.4.7-cp34-cp34m-manylinux1_x86_64.whl')
    test_msgpack('linux-x86_64-cp-35-m', 'msgpack_python-0.4.7-cp35-cp35m-manylinux1_x86_64.whl')

    ensure_failure(msgpack, msgpack_ver, 'linux-x86_64', '--no-manylinux')


def test_pex_manylinux_and_tag_selection_lxml_osx():
  with pex_manylinux_and_tag_selection_context() as (test_resolve, ensure_failure):
    test_resolve('lxml', '3.8.0', 'macosx-10.6-x86_64-cp-27-m', 'lxml-3.8.0-cp27-cp27m-macosx')
    test_resolve('lxml', '3.8.0', 'macosx-10.6-x86_64-cp-36-m', 'lxml-3.8.0-cp36-cp36m-macosx')


@pytest.mark.skipif(NOT_CPYTHON27_OR_OSX)
def test_pex_manylinux_runtime():
  """Tests resolver manylinux support and runtime resolution (and --platform=current)."""
  test_stub = dedent(
    """
    import msgpack
    print(msgpack.unpackb(msgpack.packb([1, 2, 3])))
    """
  )

  with temporary_content({'tester.py': test_stub}) as output_dir:
    pex_path = os.path.join(output_dir, 'test.pex')
    tester_path = os.path.join(output_dir, 'tester.py')
    results = run_pex_command(['--disable-cache',
                               '--no-build',
                               'msgpack-python==0.4.7',
                               '--platform=current'.format(platform),
                               '-o', pex_path])
    results.assert_success()

    out = subprocess.check_output([pex_path, tester_path])
    assert out.strip() == '[1, 2, 3]'


@pytest.mark.skipif(NOT_CPYTHON27)
def test_platform_specific_inline_egg_resolution():
  with temporary_dir() as td:
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
                           '--no-wheel',
                           'MarkupSafe==1.0',
                           '-o', pex_out_path])
    res.assert_success()


@pytest.mark.skipif(NOT_CPYTHON27)
def test_platform_specific_egg_resolution():
  with temporary_dir() as td:
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
                           '--no-wheel',
                           '--no-build',
                           '--no-pypi',
                           '--platform=linux-x86_64',
                           '--find-links=tests/example_packages/',
                           'M2Crypto==0.22.3',
                           '-o', pex_out_path])
    res.assert_success()


@pytest.mark.skipif(NOT_CPYTHON27)
def test_platform_specific_egg_resolution_matching():
  with temporary_dir() as td:
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
                           '--no-wheel',
                           '--no-build',
                           'netifaces==0.10.6',  # Only provides win32 eggs.
                           '-o', pex_out_path])
    res.assert_failure()


@pytest.mark.skipif(NOT_CPYTHON27)
def test_jupyter_appnope_env_markers():
  res = run_pex_command(['--disable-cache',
                         'jupyter==1.0.0',
                         '-c', 'jupyter',
                         '--',
                         '--version'])
  res.assert_success()
  assert len(res.output) > 4


# TODO: https://github.com/pantsbuild/pex/issues/479
@pytest.mark.skipif(NOT_CPYTHON27_OR_LINUX,
  reason='this needs to run on an interpreter with ABI type m (OSX) vs mu (linux)')
def test_cross_platform_abi_targeting_behavior():
  with temporary_dir() as td:
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
                           '--no-pypi',
                           '--platform=linux-x86_64',
                           '--find-links=tests/example_packages/',
                           'MarkupSafe==1.0',
                           '-o', pex_out_path])
    res.assert_success()


@pytest.mark.skipif(NOT_CPYTHON27)
def test_cross_platform_abi_targeting_behavior_exact():
  with temporary_dir() as td:
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['--disable-cache',
                           '--no-pypi',
                           '--platform=linux-x86_64-cp-27-mu',
                           '--find-links=tests/example_packages/',
                           'MarkupSafe==1.0',
                           '-o', pex_out_path])
    res.assert_success()


def test_pex_source_bundling():
  with temporary_dir() as output_dir:
    with temporary_dir() as input_dir:
      with open(os.path.join(input_dir, 'exe.py'), 'w') as fh:
        fh.write(dedent('''
          print('hello')
          '''
          ))

      pex_path = os.path.join(output_dir, 'pex1.pex')
      res = run_pex_command([
        '-o', pex_path,
        '-D', input_dir,
        '-e', 'exe',
      ])
      res.assert_success()

      stdout, rc = run_simple_pex(pex_path)

      assert rc == 0
      assert stdout == b'hello\n'


def test_pex_resource_bundling():
  with temporary_dir() as output_dir:
    with temporary_dir() as input_dir, temporary_dir() as resources_input_dir:
      with open(os.path.join(resources_input_dir, 'greeting'), 'w') as fh:
        fh.write('hello')
      pex_path = os.path.join(output_dir, 'pex1.pex')

      with open(os.path.join(input_dir, 'exe.py'), 'w') as fh:
        fh.write(dedent('''
          import pkg_resources
          print(pkg_resources.resource_string('__main__', 'greeting').decode('utf-8'))
          '''))

      res = run_pex_command([
        '-o', pex_path,
        '-D', input_dir,
        '-R', resources_input_dir,
        '-e', 'exe',
      ])
      res.assert_success()

      stdout, rc = run_simple_pex(pex_path)

      assert rc == 0
      assert stdout == b'hello\n'


@pytest.mark.skipif(IS_PYPY)
def test_entry_point_verification_3rdparty():
  with temporary_dir() as td:
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['Pillow==5.2.0',
                           '-e', 'PIL:Image',
                           '-o', pex_out_path,
                           '--validate-entry-point'])
    res.assert_success()


@pytest.mark.skipif(IS_PYPY)
def test_invalid_entry_point_verification_3rdparty():
  with temporary_dir() as td:
    pex_out_path = os.path.join(td, 'pex.pex')
    res = run_pex_command(['Pillow==5.2.0',
                           '-e', 'PIL:invalid',
                           '-o', pex_out_path,
                           '--validate-entry-point'])
    res.assert_failure()
