# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os


class Bootstrap(object):
  """Supports introspection of the PEX bootstrap code."""

  _INSTANCE = None

  @classmethod
  def locate(cls):
    """Locates the active PEX bootstrap.

    :rtype: :class:`Bootstrap`
    """
    if cls._INSTANCE is None:
      bootstrap_path = __file__
      module_import_path = __name__.split('.')

      # For example, our __file__ might be requests.pex/.bootstrap/pex/bootstrap.pyc and our import
      # path pex.bootstrap; so we walk back through all the module components of our import path to
      # find the base sys.path entry where we were found (requests.pex/.bootstrap in this example).
      for _ in module_import_path:
        bootstrap_path = os.path.dirname(bootstrap_path)

      cls._INSTANCE = cls(location=bootstrap_path)
    return cls._INSTANCE

  def __init__(self, location):
    self._location = location

  def demote(self):
    """Demote the bootstrap code to the end of the `sys.path` so it is found last.

    :return: The list of un-imported bootstrap modules.
    :rtype: list of :class:`types.ModuleType`
    """
    import sys  # Grab a hold of `sys` early since we'll be un-importing our module in this process.

    unimported_modules = []
    for name, module in reversed(sorted(sys.modules.items())):
      if self.imported_from_bootstrap(module):
        unimported_modules.append(sys.modules.pop(name))

    sys.path.remove(self._location)
    sys.path.append(self._location)

    return unimported_modules

  def imported_from_bootstrap(self, module):
    """Return ``True`` if the given ``module`` object was imported from bootstrap code.

    :param module: The module to check the provenance of.
    :type module: :class:`types.ModuleType`
    :rtype: bool
    """

    # A vendored module.
    path = getattr(module, '__file__', None)
    if path and path.startswith(self._location):
      return True

    # A vendored package.
    path = getattr(module, '__path__', None)
    if path:
      for path in path:
        if path.startswith(self._location):
          return True

    return False

  def __repr__(self):
    return '{cls}(location={location!r})'.format(cls=type(self).__name__, location=self._location)
