# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import os

from .tracer import TRACER


class LazyImport(object):
  _INSTANCES = {}

  @classmethod
  def runtime(cls):
    return [module_name
            for module_name, lazy_import in cls._INSTANCES.items() if lazy_import._runtime]

  @classmethod
  def for_module(cls, module_name, runtime=True):
    lazy_import = cls._INSTANCES.get(module_name)
    if lazy_import is None:
      cls._INSTANCES[module_name] = lazy_import = cls(module_name, runtime)
    return lazy_import

  def __init__(self, module_name, runtime):
    self._module_name = module_name
    self._runtime = runtime
    self._module = None

  def __getattr__(self, item):
    if self._module is None:
      self._module = importlib.import_module(self._module_name)
      TRACER.log('Lazy-loaded {}'.format(self._module), V=3)
    return getattr(self._module, item)


pkg_resources = LazyImport.for_module('pkg_resources')
wheel_install = LazyImport.for_module('wheel.install', runtime=False)


def vendor_runtime(chroot, dest_basedir, label):
  from .util import DistributionHelper
  from .vendor import vendored_dists

  module_names = {module_name.replace('.', '/'): False for module_name in LazyImport.runtime()}
  dists = vendored_dists()
  for dist in dists:
    for fn, content_stream in DistributionHelper.walk_data(dist):
      for module_name in module_names:
        if fn.startswith(module_name):
          if not fn.endswith('.pyc'):  # Sources and data only.
            dst = os.path.join(dest_basedir, fn)
            chroot.write(content_stream.read(), dst, label)
            if not module_names[module_name]:
              TRACER.log('Vendored {} from {} @ {}'.format(module_name, dist, dist.location), V=3)
            module_names[module_name] = True

  if not all(module_names.values()):
    raise RuntimeError('Failed to extract {module_names} from:\n\t{dists}'.format(
      module_names=', '.join(module for module, written in module_names.items() if not written),
      dists='\n\t'.join('{} @ {}'.format(dist, dist.location) for dist in dists)))
