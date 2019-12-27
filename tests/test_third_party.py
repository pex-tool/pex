# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from contextlib import contextmanager

from pex import third_party
from pex.common import temporary_dir
from pex.variables import ENV


@contextmanager
def temporary_pex_root():
  with temporary_dir() as pex_root, ENV.patch(PEX_ROOT=os.path.realpath(pex_root)) as env:
    original_isolated = third_party._ISOLATED
    try:
      third_party._ISOLATED = None
      yield os.path.realpath(pex_root), env
    finally:
      third_party._ISOLATED = original_isolated


def test_isolated_pex_root():
  with temporary_pex_root() as (pex_root, _):
    devendored_chroot = os.path.realpath(third_party.isolated())
    assert pex_root == os.path.commonprefix([pex_root, devendored_chroot])


def test_isolated_idempotent_inprocess():
  with temporary_pex_root():
    assert os.path.realpath(third_party.isolated()) == os.path.realpath(third_party.isolated())


def test_isolated_idempotent_subprocess():
  with temporary_pex_root() as (_, env):
    devendored_chroot = os.path.realpath(third_party.isolated())
    stdout = subprocess.check_output(
      args=[sys.executable, '-c', 'from pex.third_party import isolated; print(isolated())'],
      env=env
    )
    assert devendored_chroot == os.path.realpath(stdout.decode('utf-8').strip())
