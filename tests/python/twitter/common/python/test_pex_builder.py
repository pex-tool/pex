from contextlib import closing, contextmanager
import os
import zipfile

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_mkdir
from twitter.common.python.pex import PEX
from twitter.common.python.pex_builder import PEXBuilder
from twitter.common.python.util import DistributionHelper

from twitter.common.python.test_common import make_distribution, nested


exe_main = """
import sys
from my_package.my_module import do_something
do_something()

with open(sys.argv[1], 'w') as fp:
  fp.write('success')
"""


def write_pex(td, exe_contents, dists=None):
  dists = dists or []

  with open(os.path.join(td, 'exe.py'), 'w') as fp:
    fp.write(exe_contents)

  pb = PEXBuilder(path=td)
  for dist in dists:
    pb.add_egg(dist.location)
  pb.set_executable(os.path.join(td, 'exe.py'))
  pb.freeze()

  return pb


def test_pex_builder():
  # test w/ and w/o zipfile dists
  with nested(temporary_dir(), make_distribution('p1', zipped=True)) as (td, p1):
    write_pex(td, exe_main, dists=[p1])

    success_txt = os.path.join(td, 'success.txt')
    PEX(td).run(args=[success_txt])
    assert os.path.exists(success_txt)
    with open(success_txt) as fp:
      assert fp.read() == 'success'

  # test w/ and w/o zipfile dists
  with nested(temporary_dir(), temporary_dir(), make_distribution('p1', zipped=True)) as (
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
