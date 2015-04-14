# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import functools
import os
import subprocess
import zipfile
from hashlib import sha1
from textwrap import dedent

from twitter.common.contextutil import temporary_dir, temporary_file

from pex.common import safe_mkdir
from pex.compatibility import nested
from pex.installer import EggInstaller, WheelInstaller
from pex.pex_builder import PEXBuilder
from pex.testing import make_bdist, temporary_content, write_zipfile
from pex.util import CacheHelper, DistributionHelper

try:
  from unittest import mock
except ImportError:
  import mock


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


def test_access_zipped_assets():
  try:
    import __builtin__
    builtin_path = __builtin__.__name__
  except ImportError:
    # Python3
    import builtins
    builtin_path = builtins.__name__

  mock_open = mock.mock_open()
  with nested(mock.patch('%s.open' % builtin_path, mock_open, create=True),
      mock.patch('pex.util.resource_string', autospec=True, spec_set=True),
      mock.patch('pex.util.resource_isdir', autospec=True, spec_set=True),
      mock.patch('pex.util.resource_listdir', autospec=True, spec_set=True),
      mock.patch('pex.util.safe_mkdtemp', autospec=True, spec_set=True)) as (
          _, mock_resource_string, mock_resource_isdir, mock_resource_listdir, mock_safe_mkdtemp):

    mock_safe_mkdtemp.side_effect = iter(['tmpJIMMEH', 'faketmpDir'])
    mock_resource_listdir.side_effect = iter([['./__init__.py', './directory/'], ['file.py']])
    mock_resource_isdir.side_effect = iter([False, True, False])
    mock_resource_string.return_value = 'testing'

    temp_dir = DistributionHelper.access_zipped_assets('twitter.common', 'dirutil')

    assert mock_resource_listdir.call_count == 2
    assert mock_open.call_count == 2
    file_handle = mock_open.return_value.__enter__.return_value
    assert file_handle.write.call_count == 2
    assert mock_safe_mkdtemp.mock_calls == [mock.call()]
    assert temp_dir == 'tmpJIMMEH'


def test_access_zipped_assets_integration():
  test_executable = dedent('''
      import os
      from _pex.util import DistributionHelper
      temp_dir = DistributionHelper.access_zipped_assets('my_package', 'submodule')
      with open(os.path.join(temp_dir, 'mod.py'), 'r') as fp:
        for line in fp:
          print(line)
  ''')
  with nested(temporary_dir(), temporary_dir()) as (td1, td2):
    pb = PEXBuilder(path=td1)
    with open(os.path.join(td1, 'exe.py'), 'w') as fp:
      fp.write(test_executable)
      pb.set_executable(fp.name)

    submodule = os.path.join(td1, 'my_package', 'submodule')
    safe_mkdir(submodule)
    mod_path = os.path.join(submodule, 'mod.py')
    with open(mod_path, 'w') as fp:
      fp.write('accessed')
      pb.add_source(fp.name, 'my_package/submodule/mod.py')

    pex = os.path.join(td2, 'app.pex')
    pb.build(pex)

    po = subprocess.Popen(
        [pex],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    po.wait()
    output = po.stdout.read()
    try:
      output = output.decode('UTF-8')
    except ValueError:
      pass
    assert output == 'accessed\n'
    assert po.returncode == 0
