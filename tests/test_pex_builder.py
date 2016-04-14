# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import stat
import zipfile
from contextlib import closing

import pytest
from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_mkdir

from pex.compatibility import WINDOWS, nested
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.testing import write_simple_pex as write_pex
from pex.testing import make_bdist
from pex.util import DistributionHelper


exe_main = """
import sys
from my_package.my_module import do_something
do_something()

with open(sys.argv[1], 'w') as fp:
  fp.write('success')
"""


def test_pex_builder():
  # test w/ and w/o zipfile dists
  with nested(temporary_dir(), make_bdist('p1', zipped=True)) as (td, p1):
    write_pex(td, exe_main, dists=[p1])

    success_txt = os.path.join(td, 'success.txt')
    PEX(td).run(args=[success_txt])
    assert os.path.exists(success_txt)
    with open(success_txt) as fp:
      assert fp.read() == 'success'

  # test w/ and w/o zipfile dists
  with nested(temporary_dir(), temporary_dir(), make_bdist('p1', zipped=True)) as (
      td1, td2, p1):
    target_egg_dir = os.path.join(td2, os.path.basename(p1.location))
    safe_mkdir(target_egg_dir)
    with closing(zipfile.ZipFile(p1.location, 'r')) as zf:
      zf.extractall(target_egg_dir)
    p1 = DistributionHelper.distribution_from_path(target_egg_dir)

    write_pex(td1, exe_main, dists=[p1])

    success_txt = os.path.join(td1, 'success.txt')
    PEX(td1).run(args=[success_txt])
    assert os.path.exists(success_txt)
    with open(success_txt) as fp:
      assert fp.read() == 'success'


def test_pex_builder_shebang():
  def builder(shebang):
    pb = PEXBuilder()
    pb.set_shebang(shebang)
    return pb

  for pb in builder('foobar'), builder('#!foobar'):
    for b in pb, pb.clone():
      with temporary_dir() as td:
        target = os.path.join(td, 'foo.pex')
        b.build(target)
        expected_preamble = b'#!foobar\n'
        with open(target, 'rb') as fp:
          assert fp.read(len(expected_preamble)) == expected_preamble


def test_pex_builder_compilation():
  with nested(temporary_dir(), temporary_dir(), temporary_dir()) as (td1, td2, td3):
    src = os.path.join(td1, 'src.py')
    with open(src, 'w') as fp:
      fp.write(exe_main)

    exe = os.path.join(td1, 'exe.py')
    with open(exe, 'w') as fp:
      fp.write(exe_main)

    def build_and_check(path, precompile):
      pb = PEXBuilder(path)
      pb.add_source(src, 'lib/src.py')
      pb.set_executable(exe, 'exe.py')
      pb.freeze(bytecode_compile=precompile)
      for pyc_file in ('exe.pyc', 'lib/src.pyc', '__main__.pyc'):
        pyc_exists = os.path.exists(os.path.join(path, pyc_file))
        if precompile:
          assert pyc_exists
        else:
          assert not pyc_exists
      bootstrap_dir = os.path.join(path, PEXBuilder.BOOTSTRAP_DIR)
      bootstrap_pycs = []
      for _, _, files in os.walk(bootstrap_dir):
        bootstrap_pycs.extend(f for f in files if f.endswith('.pyc'))
      if precompile:
        assert len(bootstrap_pycs) > 0
      else:
        assert 0 == len(bootstrap_pycs)

    build_and_check(td2, False)
    build_and_check(td3, True)


@pytest.mark.skipif(WINDOWS, reason='No hardlinks on windows')
def test_pex_builder_copy_or_link():
  with nested(temporary_dir(), temporary_dir(), temporary_dir()) as (td1, td2, td3):
    src = os.path.join(td1, 'exe.py')
    with open(src, 'w') as fp:
      fp.write(exe_main)

    def build_and_check(path, copy):
      pb = PEXBuilder(path, copy=copy)
      pb.add_source(src, 'exe.py')

      path_clone = os.path.join(path, '__clone')
      pb.clone(into=path_clone)

      for root in path, path_clone:
        s1 = os.stat(src)
        s2 = os.stat(os.path.join(root, 'exe.py'))
        is_link = (s1[stat.ST_INO], s1[stat.ST_DEV]) == (s2[stat.ST_INO], s2[stat.ST_DEV])
        if copy:
          assert not is_link
        else:
          assert is_link

    build_and_check(td2, False)
    build_and_check(td3, True)
