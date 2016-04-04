# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from twitter.common.contextutil import temporary_dir

from pex.pex_builder import PEXBuilder
from pex.testing import run_simple_pex, write_simple_pex


def write_inheriting_pex(td, exe_contents, dists=None, coverage=False):
  """Write a pex file that contains an executable entry point

  :param td: temporary directory path
  :param exe_contents: entry point python file
  :type exe_contents: string
  :param dists: distributions to include, typically sdists or bdists
  :param coverage: include coverage header
  """
  dists = dists or []

  with open(os.path.join(td, 'exe.py'), 'w') as fp:
    fp.write(exe_contents)

  pb = PEXBuilder(path=td, preamble=COVERAGE_PREAMBLE if coverage else None)
  pb.info.inherit_path = True

  for dist in dists:
    pb.add_egg(dist.location)

  pb.set_executable(os.path.join(td, 'exe.py'))
  pb.freeze()

  return pb

def test_inherits_path_option():
  with temporary_dir() as td:
    pb = write_inheriting_pex(td, 'import sys\nimport os\nprint(os.environ)\nprint(sys.path)')
    pex_path = os.path.join(td, 'show_path.pex')
    pb.build(pex_path)

    env = os.environ.copy()
    env['PEX_VERBOSE'] = '1'

    so, rc = run_simple_pex(pex_path, env=env)
    assert 'Scrubbing from site-packages' not in so, 'Site packages should not be scrubbed:\n%s' % so
