# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import contextlib
from collections import OrderedDict

import pytest

from pex.bin.pex import get_interpreter
from pex.installer import WheelInstaller
from pex.testing import ensure_python_interpreter, make_installer, temporary_dir
from pex.version import SETUPTOOLS_REQUIREMENT, WHEEL_REQUIREMENT


class OrderableInstaller(WheelInstaller):
  def __init__(self, source_dir, strict=True, interpreter=None, install_dir=None, mixins=None):
    self._mixins = mixins
    super(OrderableInstaller, self).__init__(source_dir, strict, interpreter, install_dir)

  def mixins(self):
    return self._mixins


@contextlib.contextmanager
def bare_interpreter():
  with temporary_dir() as interpreter_cache:
    yield get_interpreter(
      python_interpreter=ensure_python_interpreter('3.6.3'),
      interpreter_cache_dir=interpreter_cache,
      repos=None,
      use_wheel=True
    )


@contextlib.contextmanager
def wheel_installer(*mixins):
  with bare_interpreter() as interpreter:
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
