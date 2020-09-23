# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This file contains several 2.x/3.x compatibility checkstyle violations for a reason
# checkstyle: noqa

from __future__ import absolute_import

import os
from abc import ABCMeta
from sys import version_info as sys_version_info

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, AnyStr, Text


try:
    # Python 2.x
    from ConfigParser import ConfigParser as ConfigParser
except ImportError:
    # Python 3.x
    from configparser import ConfigParser as ConfigParser  # type: ignore[import, no-redef]


AbstractClass = ABCMeta("AbstractClass", (object,), {})
PY2 = sys_version_info[0] == 2
PY3 = sys_version_info[0] == 3

string = (str,) if PY3 else (str, unicode)  # type: ignore[name-defined]

if PY2:
    from collections import Iterable as Iterable
    from collections import MutableSet as MutableSet
else:
    from collections.abc import Iterable as Iterable
    from collections.abc import MutableSet as MutableSet

if PY2:

    def to_bytes(st, encoding="utf-8"):
        # type: (AnyStr, Text) -> bytes
        if isinstance(st, unicode):
            return st.encode(encoding)
        elif isinstance(st, bytes):
            return st
        else:
            raise ValueError("Cannot convert %s to bytes" % type(st))

    def to_unicode(st, encoding="utf-8"):
        # type: (AnyStr, Text) -> Text
        if isinstance(st, unicode):
            return st
        elif isinstance(st, (str, bytes)):
            return unicode(st, encoding)
        else:
            raise ValueError("Cannot convert %s to a unicode string" % type(st))


else:

    def to_bytes(st, encoding="utf-8"):
        # type: (AnyStr, Text) -> bytes
        if isinstance(st, str):
            return st.encode(encoding)
        elif isinstance(st, bytes):
            return st
        else:
            raise ValueError("Cannot convert %s to bytes." % type(st))

    def to_unicode(st, encoding="utf-8"):
        # type: (AnyStr, Text) -> Text
        if isinstance(st, str):
            return st
        elif isinstance(st, bytes):
            return str(st, encoding)
        else:
            raise ValueError("Cannot convert %s to a unicode string" % type(st))


_PY3_EXEC_FUNCTION = """
def exec_function(ast, globals_map):
  locals_map = globals_map
  exec ast in globals_map, locals_map
  return locals_map
"""

if PY3:

    def exec_function(ast, globals_map):
        locals_map = globals_map
        exec (ast, globals_map, locals_map)
        return locals_map


else:
    # This will result in `exec_function` being defined at runtime.
    eval(compile(_PY3_EXEC_FUNCTION, "<exec_function>", "exec"))

if PY3:
    from contextlib import contextmanager, ExitStack

    @contextmanager
    def nested(*context_managers):
        enters = []
        with ExitStack() as stack:
            for manager in context_managers:
                enters.append(stack.enter_context(manager))
            yield tuple(enters)


else:
    from contextlib import nested as nested


if PY3:
    import urllib.parse as urlparse
else:
    import urlparse as urlparse


if PY3:
    from queue import Queue as Queue

    # The `os.sched_getaffinity` function appears to be supported on Linux but not OSX.
    if not hasattr(os, "sched_getaffinity"):
        from os import cpu_count as cpu_count
    else:

        def cpu_count():
            # type: () -> Optional[int]
            # The set of CPUs accessible to the current process (pid 0).
            cpu_set = os.sched_getaffinity(0)
            return len(cpu_set)


else:
    from Queue import Queue as Queue
    from multiprocessing import cpu_count as cpu_count


WINDOWS = os.name == "nt"
