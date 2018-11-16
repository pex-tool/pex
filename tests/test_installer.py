# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib

import pytest

from pex.installer import WheelInstaller
from pex.interpreter import PythonInterpreter
from pex.testing import PY36, ensure_python_interpreter, make_installer


class OrderableInstaller(WheelInstaller):
  def __init__(self, source_dir, interpreter=None, install_dir=None, mixins=None):
    self._mixins = mixins
    super(OrderableInstaller, self).__init__(source_dir, interpreter, install_dir)

  @property
  def mixins(self):
    return self._mixins


@contextlib.contextmanager
def wheel_installer(*mixins):
  bare_interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY36))
  with make_installer(installer_impl=OrderableInstaller,
                      interpreter=bare_interpreter,
                      mixins=list(mixins)) as installer:
    yield installer


def test_wheel_before_setuptools():
  with wheel_installer('wheel', 'setuptools') as installer:
    installer.bdist()


def test_setuptools_before_wheel():
  with wheel_installer('setuptools', 'wheel') as installer:
    installer.bdist()


def test_no_wheel():
  with wheel_installer('setuptools') as installer:
    with pytest.raises(installer.InstallFailure):
      installer.bdist()
