# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# import functools
import os
# import platform
# import subprocess
import sys
from textwrap import dedent

import pytest
from twitter.common.contextutil import environment_as, temporary_dir

from pex.compatibility import WINDOWS
from pex.installer import EggInstaller
from pex.testing import (
    get_dep_dist_names_from_pex,
    run_pex_command,
    run_simple_pex,
    run_simple_pex_test,
    temporary_content
)
from pex.util import DistributionHelper, named_temporary_file

# NOT_CPYTHON27_OR_36_LINUX = (
#   "hasattr(sys, 'pypy_version_info') or (platform.system() != 'Linux' and "
#   "(sys.version_info[0], sys.version_info[1]) not in [(2, 7), (3, 6)])"
# )
#
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

@pytest.mark.skipif(NOT_CPYTHON_36)
def test_pex_multi_resolve_2():
  """Tests multi-interpreter + multi-platform resolution."""
  with temporary_dir() as output_dir:
    pex_path = os.path.join(output_dir, 'pex.pex')
    results = run_pex_command(['--disable-cache',
                               'lxml==3.8.0',
                               '--platform=linux-x86_64',
                               '--platform=macosx-10.6-x86_64',
                               '--python=python2.7',
                               '-o', pex_path])
    results.assert_success()

    included_dists = get_dep_dist_names_from_pex(pex_path, 'lxml')
    assert len(included_dists) == 2
    for dist_substr in ('-cp27-', '-manylinux1_x86_64', '-macosx_'):
      assert any(dist_substr in f for f in included_dists)

# def test_pex_manylinux_and_tag_selection():
#   """Tests resolver manylinux support and tag targeting."""
#   with temporary_dir() as output_dir:
#     def do_resolve(req_name, req_version, platform, extra_flags=None):
#       extra_flags = extra_flags or ''
#       pex_path = os.path.join(output_dir, 'test.pex')
#       results = run_pex_command(['--disable-cache',
#                                  '--no-build',
#                                  '%s==%s' % (req_name, req_version),
#                                  '--platform=%s' % (platform),
#                                  '-o', pex_path] + extra_flags.split())
#       return pex_path, results
#
#     def test_resolve(req_name, req_version, platform, substr, extra_flags=None):
#       pex_path, results = do_resolve(req_name, req_version, platform, extra_flags)
#       results.assert_success()
#       included_dists = get_dep_dist_names_from_pex(pex_path, req_name.replace('-', '_'))
#       assert any(
#         substr in d for d in included_dists
#       ), 'couldnt find {} in {}'.format(substr, included_dists)
#
#     def ensure_failure(req_name, req_version, platform, extra_flags):
#       pex_path, results = do_resolve(req_name, req_version, platform, extra_flags)
#       results.assert_failure()
#
#     msgpack, msgpack_ver = 'msgpack-python', '0.4.7'
#     test_msgpack = functools.partial(test_resolve, msgpack, msgpack_ver)
#     test_msgpack('linux-x86_64', 'manylinux1_x86_64.whl')
#     test_msgpack('linux-x86_64-cp-27-m', 'msgpack_python-0.4.7-cp27-cp27m-manylinux1_x86_64.whl')
#     test_msgpack('linux-x86_64-cp-27-mu',
#                  'msgpack_python-0.4.7-cp27-cp27mu-manylinux1_x86_64.whl')
#
#     ensure_failure(msgpack, msgpack_ver, 'linux-x86_64', '--no-manylinux')


# @pytest.mark.skipif(NOT_CPYTHON27_OR_36_LINUX)
# def test_pex_manylinux_runtime():
#   """Tests resolver manylinux support and runtime resolution (and --platform=current)."""
#   test_stub = dedent(
#     """
#     import msgpack
#     print(msgpack.unpackb(msgpack.packb([1, 2, 3])))
#     """
#   )
#
#   with temporary_content({'tester.py': test_stub}) as output_dir:
#     pex_path = os.path.join(output_dir, 'test.pex')
#     tester_path = os.path.join(output_dir, 'tester.py')
#     results = run_pex_command(['--disable-cache',
#                                '--no-build',
#                                'msgpack-python==0.4.7',
#                                '--platform=current'.format(platform),
#                                '-o', pex_path])
#     results.assert_success()
#
#     out = subprocess.check_output([pex_path, tester_path])
#     assert out.strip() == '[1, 2, 3]'
