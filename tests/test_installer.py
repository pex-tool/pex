# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import contextlib
from collections import OrderedDict

import pytest

from pex.installer import WheelInstaller
from pex.interpreter import PythonInterpreter
from pex.testing import PY36, ensure_python_interpreter, make_installer
from pex.vendor import setup_interpreter
from pex.version import SETUPTOOLS_REQUIREMENT, WHEEL_REQUIREMENT


class OrderableInstaller(WheelInstaller):
  def __init__(self, source_dir, interpreter=None, install_dir=None, mixins=None):
    self._mixins = mixins
    super(OrderableInstaller, self).__init__(source_dir, interpreter, install_dir)

  def mixins(self):
    return self._mixins


def bare_interpreter(use_wheel):
  interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY36))
  return setup_interpreter(interpreter=interpreter, include_wheel=use_wheel)


@contextlib.contextmanager
def wheel_installer(*mixins):
  interpreter = bare_interpreter(use_wheel=WHEEL_EXTRA in mixins)
  with make_installer(installer_impl=OrderableInstaller,
                      interpreter=interpreter,
                      mixins=OrderedDict(mixins)) as installer:
    yield installer


WHEEL_EXTRA = ('wheel', WHEEL_REQUIREMENT)
SETUPTOOLS_EXTRA = ('setuptools', SETUPTOOLS_REQUIREMENT)


def test_wheel_before_setuptools():
  with wheel_installer(WHEEL_EXTRA, SETUPTOOLS_EXTRA) as installer:
    installer.bdist()


def test_setuptools_before_wheel():
  with wheel_installer(SETUPTOOLS_EXTRA, WHEEL_EXTRA) as installer:
    installer.bdist()


def test_no_wheel():
  with wheel_installer(SETUPTOOLS_EXTRA) as installer:
    with pytest.raises(installer.InstallFailure):
      installer.bdist()
