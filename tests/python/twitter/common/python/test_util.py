import contextlib
from hashlib import sha1
import os
import random
from textwrap import dedent
import zipfile

from twitter.common.contextutil import temporary_file, temporary_dir
from twitter.common.dirutil import safe_mkdir, safe_mkdtemp
from twitter.common.python.distiller import Distiller
from twitter.common.python.installer import Installer
from twitter.common.python.util import CacheHelper, DistributionHelper

from twitter.common.python.test_common import (
    make_distribution,
    temporary_content,
    write_zipfile,
)


def test_hash():
  empty_hash = sha1().hexdigest()

  with temporary_file() as fp:
    fp.flush()
    assert empty_hash == CacheHelper.hash(fp.name)

  with temporary_file() as fp:
    string = 'asdf' * 1024 * sha1().block_size + 'extra padding'
    fp.write(string)
    fp.flush()
    assert sha1(string.encode('utf-8')).hexdigest() == CacheHelper.hash(fp.name)

  with temporary_file() as fp:
    empty_hash = sha1()
    fp.write('asdf')
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
        zipped = write_zipfile(td, tf.name, reverse=reverse)
        with contextlib.closing(zipfile.ZipFile(tf.name, 'r')) as zf:
          zip_hash = CacheHelper.zip_hash(zf)
          assert zip_hash == dir_hash
          assert zip_hash != sha1().hexdigest()  # make sure it's not an empty hash


def test_zipsafe():
  for zipped in (False, True):
    with make_distribution(zipped=zipped) as dist:
      assert DistributionHelper.zipsafe(dist)
