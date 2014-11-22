# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import functools
import zipfile
from hashlib import sha1

from twitter.common.contextutil import temporary_file

from pex.installer import EggInstaller, WheelInstaller
from pex.testing import make_bdist, temporary_content, write_zipfile
from pex.util import CacheHelper, DistributionHelper


def test_hash():
  empty_hash = sha1().hexdigest()

  with temporary_file() as fp:
    fp.flush()
    assert empty_hash == CacheHelper.hash(fp.name)

  with temporary_file() as fp:
    string = b'asdf' * 1024 * sha1().block_size + b'extra padding'
    fp.write(string)
    fp.flush()
    assert sha1(string).hexdigest() == CacheHelper.hash(fp.name)

  with temporary_file() as fp:
    empty_hash = sha1()
    fp.write(b'asdf')
    fp.flush()
    hash_output = CacheHelper.hash(fp.name, digest=empty_hash)
    assert hash_output == empty_hash.hexdigest()


CONTENT = {
  '__main__.py': 200,
  '.deps/morfgorf': 10000,
  'twitter/__init__.py': 0,
  'twitter/common/python/foo.py': 4000,
  'twitter/common/python/bar.py': 8000,
  'twitter/common/python/bar.pyc': 6000,
}


def test_hash_consistency():
  for reverse in (False, True):
    with temporary_content(CONTENT) as td:
      dir_hash = CacheHelper.dir_hash(td)
      with temporary_file() as tf:
        write_zipfile(td, tf.name, reverse=reverse)
        with contextlib.closing(zipfile.ZipFile(tf.name, 'r')) as zf:
          zip_hash = CacheHelper.zip_hash(zf)
          assert zip_hash == dir_hash
          assert zip_hash != sha1().hexdigest()  # make sure it's not an empty hash


def test_zipsafe():
  make_egg = functools.partial(make_bdist, installer_impl=EggInstaller)
  make_whl = functools.partial(make_bdist, installer_impl=WheelInstaller)

  for zipped in (False, True):
    for zip_safe in (False, True):
      # Eggs can be zip safe
      with make_egg(zipped=zipped, zip_safe=zip_safe) as dist:
        assert DistributionHelper.zipsafe(dist) is zip_safe

      # Wheels cannot be zip safe
      with make_whl(zipped=zipped, zip_safe=zip_safe) as dist:
        assert not DistributionHelper.zipsafe(dist)

  for zipped in (False, True):
    for zip_safe in (False, True):
      with make_egg(zipped=zipped, zip_safe=zip_safe) as dist:
        assert DistributionHelper.zipsafe(dist) is zip_safe
