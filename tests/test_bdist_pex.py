# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from textwrap import dedent

from twitter.common.contextutil import pushd

from pex.testing import temporary_content


def assert_entry_points(entry_points):
  setup_py = dedent("""
      from setuptools import setup

      setup(
        name='my_app',
        version='0.0.0',
        zip_safe=True,
        packages=[''],
        entry_points=%(entry_points)r,
      )
    """ % dict(entry_points=entry_points))

  my_app = dedent("""
      def do_something():
        print("hello world!")
    """)

  with temporary_content({'setup.py': setup_py, 'my_app.py': my_app}) as project_dir:
    with pushd(project_dir):
      subprocess.check_call([sys.executable, 'setup.py', 'bdist_pex'])
      process = subprocess.Popen([os.path.join(project_dir, 'dist', 'my_app-0.0.0.pex')],
                                 stdout=subprocess.PIPE)
      stdout, _ = process.communicate()
      assert 0 == process.returncode
      assert stdout == b'hello world!\n'


def test_entry_points_dict():
  assert_entry_points({'console_scripts': ['my_app = my_app:do_something']})


def test_entry_points_ini_string():
  assert_entry_points(dedent("""
      [console_scripts]
      my_app=my_app:do_something
    """))
