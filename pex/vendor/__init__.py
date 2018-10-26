# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections
import os
import sys

from contextlib import contextmanager

from ..interpreter import PythonInterpreter
from ..third_party import pkg_resources
from ..version import SETUPTOOLS_REQUIREMENT, WHEEL_REQUIREMENT


class VendorSpec(collections.namedtuple('VendorSpec', ['key', 'version', 'target_dir'])):
  VENDOR_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), '_vendored'))

  @classmethod
  def create(cls, requirement):
    components = requirement.rsplit('==', 1)
    if len(components) != 2:
      raise ValueError('Vendored requirements must be pinned, given {!r}'.format(requirement))
    key, version = tuple(c.strip() for c in components)
    return cls(key=key, version=version, target_dir=os.path.join(cls.VENDOR_DIR, key))

  @property
  def requirement(self):
    return '{}=={}'.format(self.key, self.version)


__SETUPTOOLS = VendorSpec.create(SETUPTOOLS_REQUIREMENT)
__WHEEL = VendorSpec.create(WHEEL_REQUIREMENT)


def vendor_specs():
  return __SETUPTOOLS, __WHEEL


def adjust_sys_path(include_wheel=False):
  vendored_path = [__SETUPTOOLS.target_dir]
  if include_wheel:
    vendored_path.append(__WHEEL.target_dir)

  num_entries = len(vendored_path)
  inserted = 0
  if sys.path[:num_entries] != vendored_path:
    for path in reversed(vendored_path):
      sys.path.insert(0, path)
    inserted = len(vendored_path)
  return inserted, vendored_path


@contextmanager
def adjusted_sys_path(include_wheel=True):
  inserted_count, vendored_path = adjust_sys_path(include_wheel=include_wheel)
  try:
    yield vendored_path[:]
  finally:
    del sys.path[:inserted_count]


def vendored_dists(include_wheel=True):
  with adjusted_sys_path(include_wheel=include_wheel) as vendored_path:
    return list(pkg_resources.WorkingSet(entries=vendored_path))


def setup_interpreter(interpreter=None, include_wheel=True):
  with adjusted_sys_path(include_wheel=include_wheel):
    interpreter = interpreter or PythonInterpreter.get()
    for dist in vendored_dists(include_wheel=include_wheel):
      interpreter = interpreter.with_extra(dist.key, dist.version, dist.location)
    return interpreter
