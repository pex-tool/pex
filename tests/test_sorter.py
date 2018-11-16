# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.interpreter import PythonInterpreter
from pex.package import EggPackage, SourcePackage, WheelPackage
from pex.sorter import Sorter
from pex.third_party.pkg_resources import get_build_platform


def test_package_precedence():
  source = SourcePackage('psutil-0.6.1.tar.gz')
  egg = EggPackage('psutil-0.6.1-py2.6.egg')
  whl = WheelPackage('psutil-0.6.1-cp26-none-macosx_10_4_x86_64.whl')

  # default precedence
  assert Sorter.package_precedence(whl) > Sorter.package_precedence(egg)
  assert Sorter.package_precedence(egg) > Sorter.package_precedence(source)
  assert Sorter.package_precedence(whl) > Sorter.package_precedence(source)

  # overridden precedence
  PRECEDENCE = (EggPackage, WheelPackage)
  assert Sorter.package_precedence(source, PRECEDENCE) == (
      source.version, -1, True)  # unknown rank
  assert Sorter.package_precedence(whl, PRECEDENCE) > Sorter.package_precedence(
      source, PRECEDENCE)
  assert Sorter.package_precedence(egg, PRECEDENCE) > Sorter.package_precedence(
      whl, PRECEDENCE)


def test_sorter_sort():
  pi = PythonInterpreter.get()
  tgz = SourcePackage('psutil-0.6.1.tar.gz')
  egg = EggPackage('psutil-0.6.1-py%s-%s.egg' % (pi.python, get_build_platform()))
  whl = WheelPackage('psutil-0.6.1-cp%s-none-%s.whl' % (
      pi.python.replace('.', ''),
      get_build_platform().replace('-', '_').replace('.', '_').lower()))

  assert Sorter().sort([tgz, egg, whl]) == [whl, egg, tgz]
  assert Sorter().sort([egg, tgz, whl]) == [whl, egg, tgz]

  # test unknown type
  sorter = Sorter(precedence=(EggPackage, WheelPackage))
  assert sorter.sort([egg, tgz, whl], filter=False) == [egg, whl, tgz]
  assert sorter.sort([egg, tgz, whl], filter=True) == [egg, whl]
