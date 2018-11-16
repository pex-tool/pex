# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
import tempfile
import textwrap
from contextlib import contextmanager
from types import ModuleType

import pytest

from pex import vendor
from pex.compatibility import PY2, WINDOWS, nested, to_bytes
from pex.installer import EggInstaller, WheelInstaller
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.resolver import resolve
from pex.testing import (
    IS_PYPY,
    PY27,
    PY36,
    ensure_python_interpreter,
    make_bdist,
    make_installer,
    named_temporary_file,
    run_simple_pex_test,
    temporary_dir,
    write_simple_pex
)
from pex.util import DistributionHelper

try:
  from unittest import mock
except ImportError:
  import mock


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

  # If __path__ is not a list the module is removed; typically this implies
  # it's a namespace package (https://www.python.org/dev/peps/pep-0420/) where
  # __path__ is a _NamespacePath.
  try:
    from importlib._bootstrap_external import _NamespacePath
    bad_path = _NamespacePath("hello", "world", None)
  except ImportError:
    bad_path = {"hello": "world"}
  class FakeModule(object):
    pass
  tainted_module = FakeModule()
  tainted_module.__path__ = bad_path   # Not a list as expected
  modules = {'tainted_module': tainted_module}
  new_modules = PEX.minimum_sys_modules(['bad_path'], modules)
  assert new_modules == {}


def test_site_libs():
  with nested(mock.patch.object(PEX, '_get_site_packages'), temporary_dir()) as (
          mock_site_packages, tempdir):
    site_packages = os.path.join(tempdir, 'site-packages')
    os.mkdir(site_packages)
    mock_site_packages.return_value = set([site_packages])
    site_libs = PEX.site_libs()
    assert site_packages in site_libs


@pytest.mark.skipif(WINDOWS, reason='No symlinks on windows')
def test_site_libs_symlink():
  with nested(mock.patch.object(PEX, '_get_site_packages'), temporary_dir()) as (
          mock_site_packages, tempdir):
    site_packages = os.path.join(tempdir, 'site-packages')
    os.mkdir(site_packages)
    site_packages_link = os.path.join(tempdir, 'site-packages-link')
    os.symlink(site_packages, site_packages_link)
    mock_site_packages.return_value = set([site_packages_link])

    site_libs = PEX.site_libs()
    assert os.path.realpath(site_packages) in site_libs
    assert site_packages_link in site_libs


def test_site_libs_excludes_prefix():
  """Windows returns sys.prefix as part of getsitepackages(). Make sure to exclude it."""

  with nested(mock.patch.object(PEX, '_get_site_packages'), temporary_dir()) as (
          mock_site_packages, tempdir):
    site_packages = os.path.join(tempdir, 'site-packages')
    os.mkdir(site_packages)
    mock_site_packages.return_value = set([site_packages, sys.prefix])
    site_libs = PEX.site_libs()
    assert site_packages in site_libs
    assert sys.prefix not in site_libs


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
    assert b"Could not find script 'hello_world'" in so

    so, rc = run_simple_pex_test('', env=env_copy, dists=[bdist])
    assert rc == 0, so.decode('utf-8')
    assert b'hello world' in so

    env_copy['PEX_SCRIPT'] = 'shell_script'
    so, rc = run_simple_pex_test('', env=env_copy, dists=[bdist])
    assert rc == 1, so.decode('utf-8')
    assert b'Unable to parse' in so


def test_pex_run():
  with named_temporary_file() as fake_stdout:
    with temporary_dir() as temp_dir:
      pex = write_simple_pex(
        temp_dir,
        'import sys; sys.stdout.write("hello"); sys.stderr.write("hello"); sys.exit(0)'
      )
      rc = PEX(pex.path()).run(stdin=None, stdout=fake_stdout, stderr=fake_stdout)
      assert rc == 0

      fake_stdout.seek(0)
      assert fake_stdout.read() == b'hellohello'


def test_pex_paths():
  # Tests that PEX_PATH allows importing sources from the referenced pex.
  with named_temporary_file() as fake_stdout:
    with temporary_dir() as temp_dir:
      pex1_path = os.path.join(temp_dir, 'pex1')
      write_simple_pex(
        pex1_path,
        exe_contents='',
        sources=[
          ('foo_pkg/__init__.py', ''),
          ('foo_pkg/foo_module.py', 'def foo_func():\n  return "42"')
        ]
      )

      pex2_path = os.path.join(temp_dir, 'pex2')
      pex2 = write_simple_pex(
        pex2_path,
        'import sys; from bar_pkg.bar_module import bar_func; '
        'sys.stdout.write(bar_func()); sys.exit(0)',
        sources=[
          ('bar_pkg/__init__.py', ''),
          ('bar_pkg/bar_module.py',
           'from foo_pkg.foo_module import foo_func\ndef bar_func():\n  return foo_func()')
        ]
      )

      rc = PEX(pex2.path()).run(stdin=None, stdout=fake_stdout, env={'PEX_PATH': pex1_path})
      assert rc == 0

      fake_stdout.seek(0)
      assert fake_stdout.read() == b'42'


@contextmanager
def _add_test_hello_to_pex(ep):
  with tempfile.NamedTemporaryFile() as tf:
    tf.write(b'def hello(): print("hello")')
    tf.flush()

    pex_builder = PEXBuilder()
    pex_builder.add_source(tf.name, 'test.py')
    pex_builder.set_entry_point(ep)
    pex_builder.freeze()
    yield pex_builder


def test_pex_verify_entry_point_method_should_pass():
  with _add_test_hello_to_pex('test:hello') as pex_builder:
    # No error should happen here because `test:hello` is correct
    PEX(pex_builder.path(),
        interpreter=pex_builder.interpreter,
        verify_entry_point=True)


def test_pex_verify_entry_point_module_should_pass():
  with _add_test_hello_to_pex('test') as pex_builder:
    # No error should happen here because `test` is correct
    PEX(pex_builder.path(),
        interpreter=pex_builder.interpreter,
        verify_entry_point=True)


def test_pex_verify_entry_point_method_should_fail():
  with _add_test_hello_to_pex('test:invalid_entry_point') as pex_builder:
    # Expect InvalidEntryPoint due to invalid entry point method
    with pytest.raises(PEX.InvalidEntryPoint):
      PEX(pex_builder.path(),
          interpreter=pex_builder.interpreter,
          verify_entry_point=True)


def test_pex_verify_entry_point_module_should_fail():
  with _add_test_hello_to_pex('invalid.module') as pex_builder:
    # Expect InvalidEntryPoint due to invalid entry point module
    with pytest.raises(PEX.InvalidEntryPoint):
      PEX(pex_builder.path(),
          interpreter=pex_builder.interpreter,
          verify_entry_point=True)


@pytest.mark.skipif(IS_PYPY)
def test_activate_interpreter_different_from_current():
  with temporary_dir() as pex_root:
    interp_version = PY36 if PY2 else PY27
    custom_interpreter = vendor.setup_interpreter(
      interpreter=PythonInterpreter.from_binary(ensure_python_interpreter(interp_version)),
    )
    pex_info = PexInfo.default(custom_interpreter)
    pex_info.pex_root = pex_root
    with temporary_dir() as pex_chroot:
      pex_builder = PEXBuilder(path=pex_chroot,
                               interpreter=custom_interpreter,
                               pex_info=pex_info)
      with make_bdist(installer_impl=WheelInstaller, interpreter=custom_interpreter) as bdist:
        pex_builder.add_distribution(bdist)
        pex_builder.set_entry_point('sys:exit')
        pex_builder.freeze()

        pex = PEX(pex_builder.path(), interpreter=custom_interpreter)
        try:
          pex._activate()
        except SystemExit as e:
          pytest.fail('PEX activation of %s failed with %s' % (pex, e))


def test_execute_interpreter_dashc_program():
  with temporary_dir() as pex_chroot:
    pex_builder = PEXBuilder(path=pex_chroot)
    pex_builder.freeze()
    process = PEX(pex_chroot).run(args=['-c', 'import sys; print(" ".join(sys.argv))', 'one'],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  blocking=False)
    stdout, stderr = process.communicate()

    assert 0 == process.returncode
    assert b'-c one\n' == stdout
    assert b'' == stderr


def test_execute_interpreter_dashm_module():
  with temporary_dir() as pex_chroot:
    interpreter = vendor.setup_interpreter()
    pex_builder = PEXBuilder(path=pex_chroot, interpreter=interpreter)
    pex_builder.add_source(None, 'foo/__init__.py')
    with tempfile.NamedTemporaryFile() as fp:
      fp.write(b'import sys; print(" ".join(sys.argv))')
      fp.flush()
      pex_builder.add_source(fp.name, 'foo/bar.py')
    pex_builder.freeze()
    pex = PEX(pex_chroot, interpreter=vendor.setup_interpreter())
    process = pex.run(args=['-m', 'foo.bar', 'one', 'two'],
                      stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE,
                      blocking=False)
    stdout, stderr = process.communicate()

    assert 0 == process.returncode
    assert b'foo.bar one two\n' == stdout
    assert b'' == stderr


def test_execute_interpreter_stdin_program():
  with temporary_dir() as pex_chroot:
    pex_builder = PEXBuilder(path=pex_chroot)
    pex_builder.freeze()
    process = PEX(pex_chroot).run(args=['-', 'one', 'two'],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  stdin=subprocess.PIPE,
                                  blocking=False)
    stdout, stderr = process.communicate(input=b'import sys; print(" ".join(sys.argv))')

    assert 0 == process.returncode
    assert b'- one two\n' == stdout
    assert b'' == stderr


def test_execute_interpreter_file_program():
  with temporary_dir() as pex_chroot:
    pex_builder = PEXBuilder(path=pex_chroot)
    pex_builder.freeze()
    with tempfile.NamedTemporaryFile() as fp:
      fp.write(b'import sys; print(" ".join(sys.argv))')
      fp.flush()
      process = PEX(pex_chroot).run(args=[fp.name, 'one', 'two'],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    blocking=False)
      stdout, stderr = process.communicate()

      assert 0 == process.returncode
      assert '{} one two\n'.format(fp.name).encode('utf-8') == stdout
      assert b'' == stderr


def test_pex_run_custom_setuptools_useable():
  with temporary_dir() as resolve_cache:
    dists = [resolved_dist.distribution
             for resolved_dist in resolve(['setuptools==36.2.7'], cache=resolve_cache)]
    with temporary_dir() as temp_dir:
      pex = write_simple_pex(
        temp_dir,
        'from setuptools.sandbox import run_setup',
        dists=dists,
      )
      rc = PEX(pex.path()).run()
      assert rc == 0


def test_pex_run_conflicting_custom_setuptools_useable():
  # Here we use our vendored, newer setuptools to build the pex which has an older setuptools
  # requirement. These setuptools dists have different pkg_resources APIs:
  # $ diff \
  #   <(zipinfo -1 setuptools-20.3.1-py2.py3-none-any.whl | grep pkg_resources/ | sort) \
  #   <(zipinfo -1 setuptools-40.6.2-py2.py3-none-any.whl | grep pkg_resources/ | sort)
  # 2a3,4
  # > pkg_resources/py31compat.py
  # > pkg_resources/_vendor/appdirs.py
  with temporary_dir() as resolve_cache:
    dists = [resolved_dist.distribution
             for resolved_dist in resolve(['setuptools==20.3.1'], cache=resolve_cache)]
    with temporary_dir() as temp_dir:
      pex = write_simple_pex(
        temp_dir,
        exe_contents=textwrap.dedent("""
          import sys
          import pkg_resources
          
          try:
            from pkg_resources import appdirs
            sys.exit(1)
          except ImportError:
            pass
  
          try:
            from pkg_resources import py31compat
            sys.exit(2)
          except ImportError:
            pass
        """),
        dists=dists,
      )
      rc = PEX(pex.path()).run(env={'PEX_VERBOSE': '9'})
      assert rc == 0
