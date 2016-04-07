# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from pkg_resources import Requirement, parse_version

from pex.package import EggPackage, SourcePackage


def test_source_packages():
  for ext in ('.tar.gz', '.tar', '.tgz', '.zip', '.tar.bz2'):
    sl = SourcePackage('a_p_r-3.1.3' + ext)
    assert sl._name == 'a_p_r'
    assert sl.name == 'a-p-r'
    assert sl.raw_version == '3.1.3'
    assert sl.version == parse_version(sl.raw_version)
    for req in ('a_p_r', 'a_p_r>2', 'a_p_r>3', 'a_p_r>=3.1.3', 'a_p_r==3.1.3', 'a_p_r>3,<3.5'):
      assert sl.satisfies(req)
      assert sl.satisfies(Requirement.parse(req))
    for req in ('foo', 'a_p_r==4.0.0', 'a_p_r>4.0.0', 'a_p_r>3.0.0,<3.0.3', 'a==3.1.3'):
      assert not sl.satisfies(req)
  sl = SourcePackage('python-dateutil-1.5.tar.gz')
  assert sl.name == 'python-dateutil'
  assert sl.raw_version == '1.5'


def test_local_specifier():
  for ext in ('.tar.gz', '.tar', '.tgz', '.zip', '.tar.bz2'):
    sl = SourcePackage('a_p_r-3.1.3+pexed.1' + ext)
    assert sl.name == 'a-p-r'
    assert sl.raw_version == '3.1.3+pexed.1'
    assert sl.version == parse_version(sl.raw_version)
    assert sl.satisfies('a_p_r==3.1.3+pexed.1')


def test_egg_packages():
  el = EggPackage('psutil-0.4.1-py2.6-macosx-10.7-intel.egg')
  assert el.name == 'psutil'
  assert el.raw_version == '0.4.1'
  assert el.py_version == '2.6'
  assert el.platform == 'macosx-10.7-intel'
  for req in ('psutil', 'psutil>0.4', 'psutil==0.4.1', 'psutil>0.4.0,<0.4.2'):
    assert el.satisfies(req)
  for req in ('foo', 'bar==0.4.1'):
    assert not el.satisfies(req)

  # Legacy pkg_resources normalized version numbers.
  el = EggPackage('pyfoo-1.0.0_bar-py2.7-linux-x86_64.egg')
  assert el.name == 'pyfoo'
  assert el.raw_version == '1.0.0-bar'
  assert el.py_version == '2.7'
  assert el.platform == 'linux-x86_64'
  for req in ('pyfoo', 'pyfoo==1.0.0-bar'):
    assert el.satisfies(req)

  el = EggPackage('pytz-2012b-py2.6.egg')
  assert el.name == 'pytz'
  assert el.raw_version == '2012b0'
  assert el.py_version == '2.6'
  assert el.platform is None

  # Eggs must have their own version and a python version.
  with pytest.raises(EggPackage.InvalidPackage):
    EggPackage('bar.egg')

  with pytest.raises(EggPackage.InvalidPackage):
    EggPackage('bar-1.egg')

  with pytest.raises(EggPackage.InvalidPackage):
    EggPackage('bar-py2.6.egg')
