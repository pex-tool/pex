# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import zipfile
from contextlib import closing

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_mkdir

from pex.compatibility import nested
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
  pb = PEXBuilder()
  pb.set_shebang('foobar')

  with temporary_dir() as td:
    target = os.path.join(td, 'foo.pex')
    pb.build(target)
    expected_preamble = b'#!foobar\n'
    with open(target, 'rb') as fp:
      assert fp.read(len(expected_preamble)) == expected_preamble
