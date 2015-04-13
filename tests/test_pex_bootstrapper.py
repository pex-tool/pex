# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import zipfile
from contextlib import closing

from twitter.common.contextutil import temporary_dir

from pex.pex_bootstrapper import get_pex_info
from pex.testing import write_simple_pex


def test_get_pex_info():
  with temporary_dir() as td:
    pb = write_simple_pex(td, 'print("hello world!")')
    pex_path = os.path.join(td, 'hello_world.pex')
    pb.build(pex_path)

    # from zip
    pex_info = get_pex_info(pex_path)

    with temporary_dir() as pex_td:
      with closing(zipfile.ZipFile(pex_path, 'r')) as zf:
        zf.extractall(pex_td)

      # from dir
      pex_info_2 = get_pex_info(pex_td)

      # same when encoded
      assert pex_info.dump() == pex_info_2.dump()
