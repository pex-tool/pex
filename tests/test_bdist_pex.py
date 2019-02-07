# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import stat
import subprocess
import sys
from contextlib import contextmanager
from textwrap import dedent

from pex.common import open_zip
from pex.installer import WheelInstaller
from pex.testing import temporary_content, temporary_dir


def bdist_pex_setup_py(**kwargs):
  return dedent("""
    from pex.commands.bdist_pex import bdist_pex
    from setuptools import setup

    setup(cmdclass={{'bdist_pex': bdist_pex}}, **{kwargs!r})
  """.format(kwargs=kwargs))


@contextmanager
def bdist_pex(project_dir, bdist_args=None):
  with temporary_dir() as dist_dir:
    cmd = [sys.executable, 'setup.py', 'bdist_pex', '--bdist-dir={}'.format(dist_dir)]
    if bdist_args:
      cmd.extend(bdist_args)
    subprocess.check_call(cmd, cwd=project_dir)
    dists = os.listdir(dist_dir)
    assert len(dists) == 1
    yield os.path.join(dist_dir, dists[0])


def assert_entry_points(entry_points):
  setup_py = bdist_pex_setup_py(name='my_app',
                                version='0.0.0',
                                zip_safe=True,
                                packages=[''],
                                entry_points=entry_points)
  my_app = dedent("""
      def do_something():
        print("hello world!")
    """)

  with temporary_content({'setup.py': setup_py, 'my_app.py': my_app}) as project_dir:
    with bdist_pex(project_dir) as my_app_pex:
      process = subprocess.Popen([my_app_pex], stdout=subprocess.PIPE)
      stdout, _ = process.communicate()
      assert '{pex_root}' not in os.listdir(project_dir)
      assert 0 == process.returncode
      assert stdout == b'hello world!\n'


def assert_pex_args_shebang(shebang):
  setup_py = bdist_pex_setup_py(name='my_app',
                                version='0.0.0',
                                zip_safe=True,
                                packages=[''])

  with temporary_content({'setup.py': setup_py}) as project_dir:
    pex_args = '--pex-args=--python-shebang="{}"'.format(shebang)
    with bdist_pex(project_dir, bdist_args=[pex_args]) as my_app_pex:
      with open(my_app_pex, 'rb') as fp:
        assert fp.readline().decode().rstrip() == shebang


def test_entry_points_dict():
  assert_entry_points({'console_scripts': ['my_app = my_app:do_something']})


def test_entry_points_ini_string():
  assert_entry_points(dedent("""
      [console_scripts]
      my_app=my_app:do_something
    """))


def test_pex_args_shebang_with_spaces():
  assert_pex_args_shebang('#!/usr/bin/env python')


def test_pex_args_shebang_without_spaces():
  assert_pex_args_shebang('#!/usr/bin/python')


def test_unwriteable_contents():
  my_app_setup_py = dedent("""
      from setuptools import setup

      setup(
        name='my_app',
        version='0.0.0',
        zip_safe=True,
        packages=['my_app'],
        include_package_data=True,
        package_data={'my_app': ['unwriteable.so']},
      )
    """)

  UNWRITEABLE_PERMS = 0o400
  with temporary_content({'setup.py': my_app_setup_py,
                          'my_app/__init__.py': '',
                          'my_app/unwriteable.so': ''},
                         perms=UNWRITEABLE_PERMS) as my_app_project_dir:
    my_app_whl = WheelInstaller(my_app_project_dir).bdist()

    uses_my_app_setup_py = bdist_pex_setup_py(name='uses_my_app',
                                              version='0.0.0',
                                              zip_safe=True,
                                              install_requires=['my_app'])
    with temporary_content({'setup.py': uses_my_app_setup_py}) as uses_my_app_project_dir:
      pex_args = '--pex-args=--disable-cache --no-pypi -f {}'.format(os.path.dirname(my_app_whl))
      with bdist_pex(uses_my_app_project_dir, bdist_args=[pex_args]) as uses_my_app_pex:
        with open_zip(uses_my_app_pex) as zf:
          unwriteable_sos = [path for path in zf.namelist()
                             if path.endswith('my_app/unwriteable.so')]
          assert 1 == len(unwriteable_sos)
          unwriteable_so = unwriteable_sos.pop()
          zf.extract(unwriteable_so, path=uses_my_app_project_dir)
          extract_dest = os.path.join(uses_my_app_project_dir, unwriteable_so)
          assert UNWRITEABLE_PERMS == stat.S_IMODE(os.stat(extract_dest).st_mode)
