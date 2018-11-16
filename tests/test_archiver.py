# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import os
from zipfile import ZipFile

from pex.archiver import Archiver
from pex.testing import temporary_dir


def test_package_fetch_without_location():
  with temporary_dir() as td:
    dateutil_base = 'python-dateutil-1.5'
    dateutil = '%s.zip' % dateutil_base

    with contextlib.closing(ZipFile(os.path.join(td, dateutil), 'w')) as zf:
      zf.writestr(os.path.join(dateutil_base, 'file1.txt'), 'junk1')
      zf.writestr(os.path.join(dateutil_base, 'file2.txt'), 'junk2')

    dest = Archiver.unpack(zf.filename)
    assert set(os.listdir(dest)) == set(['file1.txt', 'file2.txt'])

    with temporary_dir() as td2:
      dest = Archiver.unpack(zf.filename, location=td2)
      assert set(os.listdir(os.path.join(td2, 'python-dateutil-1.5'))) == set(
          ['file1.txt', 'file2.txt'])
