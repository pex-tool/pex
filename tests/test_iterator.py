# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pkg_resources import Requirement, get_build_platform

from pex.interpreter import PythonInterpreter
from pex.iterator import Iterator
from pex.package import EggPackage, SourcePackage, WheelPackage


def test_package_precedence():
  source = SourcePackage('psutil-0.6.1.tar.gz')
  egg = EggPackage('psutil-0.6.1-py2.6.egg')
  whl = WheelPackage('psutil-0.6.1-cp26-none-macosx_10_4_x86_64.whl')

  # default precedence
  assert Iterator.package_precedence(whl) > Iterator.package_precedence(egg)
  assert Iterator.package_precedence(egg) > Iterator.package_precedence(source)
  assert Iterator.package_precedence(whl) > Iterator.package_precedence(source)

  # overridden precedence
  PRECEDENCE = (EggPackage, WheelPackage)
  assert Iterator.package_precedence(source, PRECEDENCE) == (
      source.version, -1, True)  # unknown rank
  assert Iterator.package_precedence(whl, PRECEDENCE) > Iterator.package_precedence(
      source, PRECEDENCE)
  assert Iterator.package_precedence(egg, PRECEDENCE) > Iterator.package_precedence(
      whl, PRECEDENCE)


class FakeCrawler(object):
  def __init__(self, hrefs):
    self._hrefs = hrefs
    self.opener = None

  def crawl(self, *args, **kw):
    return self._hrefs


class FakeIterator(Iterator):
  def __init__(self, links):
    self.__links = list(links)
    super(FakeIterator, self).__init__(crawler=FakeCrawler([]))

  def _iter_unordered(self, *_, **__):
    return iter(self.__links)


def test_iter_ordering():
  pi = PythonInterpreter.get()
  tgz = SourcePackage('psutil-0.6.1.tar.gz')
  egg = EggPackage('psutil-0.6.1-py%s-%s.egg' % (pi.python, get_build_platform()))
  whl = WheelPackage('psutil-0.6.1-cp%s-none-%s.whl' % (
      pi.python.replace('.', ''),
      get_build_platform().replace('-', '_').replace('.', '_').lower()))
  req = Requirement.parse('psutil')

  assert list(FakeIterator([tgz, egg, whl]).iter(req)) == [whl, egg, tgz]
  assert list(FakeIterator([egg, tgz, whl]).iter(req)) == [whl, egg, tgz]


def test_href_translation():
  VERSIONS = ['0.4.0', '0.4.1', '0.5.0', '0.6.0']

  def fake_link(version):
    return 'http://www.example.com/foo/bar/psutil-%s.tar.gz' % version

  fc = FakeCrawler([fake_link(v) for v in VERSIONS])
  ob = Iterator(crawler=fc)

  for v in VERSIONS:
    pkgs = list(ob.iter(Requirement.parse('psutil==%s' % v)))
    assert len(pkgs) == 1, 'Version: %s' % v
    assert pkgs[0] == SourcePackage(fake_link(v))

  assert list(ob.iter(Requirement.parse('psutil>=0.5.0'))) == [
    SourcePackage(fake_link('0.6.0')),
    SourcePackage(fake_link('0.5.0'))]

  assert list(ob.iter(Requirement.parse('psutil'))) == [
      SourcePackage(fake_link(v)) for v in reversed(VERSIONS)]
