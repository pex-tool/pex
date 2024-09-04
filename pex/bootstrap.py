# coding=utf-8
# Copyright 2018 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import sys
import types

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List


class Bootstrap(object):
    """Supports introspection of the PEX bootstrap code."""

    _INSTANCE = None

    @classmethod
    def locate(cls):
        # type: () -> Bootstrap
        """Locates the active PEX bootstrap.

        :rtype: :class:`Bootstrap`
        """
        if cls._INSTANCE is None:
            bootstrap_path = __file__
            module_import_path = __name__.split(".")

            # For example, our __file__ might be requests.pex/.bootstrap/pex/bootstrap.pyc and our import
            # path pex.bootstrap; so we walk back through all the module components of our import path to
            # find the base sys.path entry where we were found (requests.pex/.bootstrap in this example).
            for _ in module_import_path:
                bootstrap_path = os.path.dirname(bootstrap_path)

            cls._INSTANCE = cls(sys_path_entry=bootstrap_path)
        return cls._INSTANCE

    def __init__(self, sys_path_entry):
        # type: (str) -> None
        self._sys_path_entry = sys_path_entry
        self._realpath = os.path.realpath(self._sys_path_entry)

    @property
    def path(self):
        # type: () -> str
        return self._sys_path_entry

    def demote(self, disable_vendor_importer=True):
        # type: (bool) -> List[types.ModuleType]
        """Demote the bootstrap code to the end of the `sys.path` so it is found last.

        :return: The list of un-imported bootstrap modules.
        :rtype: list of :class:`types.ModuleType`
        """
        # Grab a hold of `sys` early since we'll be un-importing our module in this process.
        import sys

        # N.B.: We mutate the sys.path before un-importing modules so that any re-imports triggered
        # by concurrent code will pull from the desired sys.path ordering.
        # See here for how this situation might arise: https://github.com/pex-tool/pex/issues/1272

        sys.path[:] = [path for path in sys.path if os.path.realpath(path) != self._realpath]
        sys.path.append(self._sys_path_entry)

        unimported_modules = []  # type: List[types.ModuleType]
        for name, module in reversed(sorted(sys.modules.items())):
            if "pex.cache.access" == name:
                # N.B.: The pex.cache.access module maintains cache lock state which must be
                # preserved in the case of a Pex PEX.
                module.save_lock_state()
            if "pex.third_party" == name and not disable_vendor_importer:
                continue
            if self.imported_from_bootstrap(module):
                unimported_modules.append(sys.modules.pop(name))
        return unimported_modules

    def imported_from_bootstrap(self, module):
        # type: (Any) -> bool
        """Return ``True`` if the given ``module`` object was imported from bootstrap code.

        :param module: The module to check the provenance of.
        """

        # Python 2.7 does some funky imports in the email stdlib package that cause havoc with
        # un-importing. Since all our own importing just goes through the vanilla importers we can
        # safely ignore all but the standard module type.
        if not isinstance(module, types.ModuleType):
            return False

        # A vendored module.
        path = getattr(module, "__file__", None)
        if path and os.path.realpath(path).startswith(self._realpath):
            return True

        # A vendored package.
        path = getattr(module, "__path__", None)
        if path and any(
            os.path.realpath(path_item).startswith(self._realpath) for path_item in path
        ):
            return True

        return False

    def __repr__(self):
        # type: () -> str
        return "{cls}(sys_path_entry={sys_path_entry!r})".format(
            cls=type(self).__name__, sys_path_entry=self._sys_path_entry
        )


def demote(disable_vendor_importer=True):
    # type: (bool) -> None
    """Demote PEX bootstrap code to the end of `sys.path` and uninstall all PEX vendored code."""

    from . import third_party
    from .tracer import TRACER

    TRACER.log("Bootstrap complete, performing final sys.path modifications...")

    should_log = {level: TRACER.should_log(V=level) for level in range(1, 10)}

    def log(msg, V=1):
        if should_log.get(V, False):
            print("pex: {}".format(msg), file=sys.stderr)

    # Remove the third party resources pex uses and demote pex bootstrap code to the end of
    # sys.path for the duration of the run to allow conflicting versions supplied by user
    # dependencies to win during the course of the execution of user code.
    third_party.uninstall()

    bootstrap = Bootstrap.locate()
    log("Demoting code from %s" % bootstrap, V=2)
    for module in bootstrap.demote(disable_vendor_importer=disable_vendor_importer):
        log("un-imported {}".format(module), V=9)

    import pex

    log("Re-imported pex from {}".format(pex.__path__), V=3)

    log("PYTHONPATH contains:")
    for element in sys.path:
        log("  %c %s" % (" " if os.path.exists(element) else "*", element))
    log("  * - paths that do not exist or will be imported via zipimport")
