# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager

from twitter.common.contextutil import environment_as, temporary_dir

from pex.pex_builder import PEXBuilder
from pex.testing import run_simple_pex


@contextmanager
def write_and_run_simple_pex(inheriting=False):
  """Write a pex file that contains an executable entry point

  :param inheriting: whether this pex should inherit site-packages paths
  :type inheriting: bool
  """
  with temporary_dir() as td:
    pex_path = os.path.join(td, 'show_path.pex')
    with open(os.path.join(td, 'exe.py'), 'w') as fp:
      fp.write('')  # No contents, we just want the startup messages

    pb = PEXBuilder(path=td, preamble=None)
    pb.info.inherit_path = inheriting
    pb.set_executable(os.path.join(td, 'exe.py'))
    pb.freeze()
    pb.build(pex_path)
    with environment_as(PEX_VERBOSE='1'):
      yield run_simple_pex(pex_path)[0]


def test_inherits_path_option():
  with write_and_run_simple_pex(inheriting=True) as so:
    assert 'Scrubbing from site-packages' not in str(so), 'Site packages should not be scrubbed.'


def test_does_not_inherit_path_option():
  with write_and_run_simple_pex(inheriting=False) as so:
    assert 'Scrubbing from site-packages' in str(so), 'Site packages should be scrubbed.'
