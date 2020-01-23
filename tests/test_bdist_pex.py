# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from contextlib import contextmanager
from textwrap import dedent

from pex.common import open_zip, temporary_dir
from pex.interpreter import spawn_python_job
from pex.testing import WheelBuilder, make_project, temporary_content


@contextmanager
def bdist_pex(project_dir, bdist_args=None):
  with temporary_dir() as dist_dir:
    cmd = ['setup.py', 'bdist_pex', '--bdist-dir={}'.format(dist_dir)]
    if bdist_args:
      cmd.extend(bdist_args)

    spawn_python_job(args=cmd, cwd=project_dir).wait()
    dists = os.listdir(dist_dir)
    assert len(dists) == 1
    yield os.path.join(dist_dir, dists[0])


def assert_entry_points(entry_points):
  with make_project(name='my_app', entry_points=entry_points) as project_dir:
    with bdist_pex(project_dir) as my_app_pex:
      process = subprocess.Popen([my_app_pex], stdout=subprocess.PIPE)
      stdout, _ = process.communicate()
      assert '{pex_root}' not in os.listdir(project_dir)
      assert 0 == process.returncode
      assert stdout == b'hello world!\n'


def assert_pex_args_shebang(shebang):
  with make_project() as project_dir:
    pex_args = '--pex-args=--python-shebang="{}"'.format(shebang)
    with bdist_pex(project_dir, bdist_args=[pex_args]) as my_app_pex:
      with open(my_app_pex, 'rb') as fp:
        assert fp.readline().decode().rstrip() == shebang


def test_entry_points_dict():
  assert_entry_points({'console_scripts': ['my_app = my_app.my_module:do_something']})


def test_entry_points_ini_string():
  assert_entry_points(dedent("""
      [console_scripts]
      my_app=my_app.my_module:do_something
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
                          'my_app/unwriteable.so': 'so contents'},
                         perms=UNWRITEABLE_PERMS) as my_app_project_dir:
    my_app_whl = WheelBuilder(my_app_project_dir).bdist()

    with make_project(name='uses_my_app', install_reqs=['my_app']) as uses_my_app_project_dir:
      pex_args = '--pex-args=--disable-cache --no-pypi -f {}'.format(os.path.dirname(my_app_whl))
      with bdist_pex(uses_my_app_project_dir, bdist_args=[pex_args]) as uses_my_app_pex:
        with open_zip(uses_my_app_pex) as zf:
          unwriteable_sos = [path for path in zf.namelist()
                             if path.endswith('my_app/unwriteable.so')]
          assert 1 == len(unwriteable_sos)
          unwriteable_so = unwriteable_sos.pop()
          zf.extract(unwriteable_so, path=uses_my_app_project_dir)
          extract_dest = os.path.join(uses_my_app_project_dir, unwriteable_so)
          with open(extract_dest) as fp:
            assert 'so contents' == fp.read()
