# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from pkg_resources import Requirement, parse_version

from pex.package import EggPackage, SourcePackage, WheelPackage


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


def test_wheel_package():
  wp = WheelPackage(
      'file:///home/user/.pex/build/requests-2.12.1-py2.py3-none-any.whl'
  )
  assert wp.name == "requests"
  assert wp.raw_version == "2.12.1"
  assert wp._py_tag == "py2.py3"
  assert wp._abi_tag == "none"
  assert wp._arch_tag == "any"


@pytest.mark.parametrize("package_name", [
  "transmute_core-0.4.5-py2.py3-none.whl"
])
def test_invalid_wheel_package_name(package_name):
  with pytest.raises(WheelPackage.InvalidPackage):
    WheelPackage(package_name)


def test_different_wheel_packages_should_be_equal():
  pypi_package = WheelPackage(
    'https://pypi.python.org/packages/9b/31/'
    'e9925a2b9a06f97c3450bac6107928d3533bfe64ca5615442504104321e8/'
    'requests-2.12.1-py2.py3-none-any.whl'
  )
  local_package = WheelPackage(
    'https://internalpypi.mycompany.org/packages/9b/31/'
    'e9925a2b9a06f97c3450bac6107928d3533bfe64ca5615442504104321e8/'
    'requests-2.12.1-py2.py3-none-any.whl'
  )
  assert pypi_package == local_package


def test_prereleases():
  def source_package(version):
    return SourcePackage('setuptools-%s.tar.gz' % version)

  def egg_package(version):
    return EggPackage('setuptools-%s-py2.7.egg' % version)

  def wheel_package(version):
    return WheelPackage('file:///tmp/setuptools-%s-py2.py3-none-any.whl' % version)

  requirement = 'setuptools>=6,<8'

  for package in (egg_package, source_package, egg_package, wheel_package):
    stable_package = package('7.0')
    assert stable_package.satisfies(requirement)
    assert stable_package.satisfies(requirement, allow_prereleases=False)
    assert stable_package.satisfies(requirement, allow_prereleases=True)

    prerelease_package = package('7.0b1')

    # satisfies should exclude prereleases by default.
    assert not prerelease_package.satisfies(requirement)

    assert not prerelease_package.satisfies(requirement, allow_prereleases=False)
    assert prerelease_package.satisfies(requirement, allow_prereleases=True)


def test_explicit_prereleases():
  def source_package(version):
    return SourcePackage('setuptools-%s.tar.gz' % version)

  def egg_package(version):
    return EggPackage('setuptools-%s-py2.7.egg' % version)

  def wheel_package(version):
    return WheelPackage('file:///tmp/setuptools-%s-py2.py3-none-any.whl' % version)

  requirement = 'setuptools==7.0b1'

  for package in (egg_package, source_package, egg_package, wheel_package):
    prerelease_package = package('7.0b1')

    # satisfies should not exclude prereleases if explicitly requested
    assert prerelease_package.satisfies(requirement)
