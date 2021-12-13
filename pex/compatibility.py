# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This file contains several 2.x/3.x compatibility checkstyle violations for a reason
# checkstyle: noqa

from __future__ import absolute_import

import os
import re
import sys
from abc import ABCMeta
from io import BytesIO
from sys import version_info as sys_version_info

from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Optional, AnyStr, Text, Tuple, Type


try:
    # Python 2.x
    from ConfigParser import ConfigParser as ConfigParser
except ImportError:
    # Python 3.x
    from configparser import ConfigParser as ConfigParser  # type: ignore[import, no-redef]


AbstractClass = ABCMeta("AbstractClass", (object,), {})
PY2 = sys_version_info[0] == 2
PY3 = sys_version_info[0] == 3

string = cast("Tuple[Type, ...]", (str,) if PY3 else (str, unicode))  # type: ignore[name-defined]

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

    def exec_function(ast, globals_map):
        raise AssertionError("Expected this function to be re-defined at runtime.")

    # This will result in `exec_function` being re-defined at runtime.
    eval(compile(_PY3_EXEC_FUNCTION, "<exec_function>", "exec"))


if PY3:
    from urllib import parse as urlparse

    from urllib.error import HTTPError as HTTPError
    from urllib.request import build_opener as build_opener
    from urllib.request import FileHandler as FileHandler
    from urllib.request import HTTPSHandler as HTTPSHandler
    from urllib.request import ProxyHandler as ProxyHandler
    from urllib.request import Request as Request
else:
    import urlparse as urlparse

    from urllib2 import build_opener as build_opener
    from urllib2 import FileHandler as FileHandler
    from urllib2 import HTTPError as HTTPError
    from urllib2 import HTTPSHandler as HTTPSHandler
    from urllib2 import ProxyHandler as ProxyHandler
    from urllib2 import Request as Request

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


# Universal newlines is the default in Python 3.
MODE_READ_UNIVERSAL_NEWLINES = "rU" if PY2 else "r"


def get_stdout_bytes_buffer():
    # type: () -> BytesIO
    return cast(BytesIO, getattr(sys.stdout, "buffer", sys.stdout))


if PY3:
    is_valid_python_identifier = str.isidentifier
else:

    def is_valid_python_identifier(text):
        # type: (str) -> bool

        # N.B.: Python 2.7 only supports ASCII characters so the check is easy and this is probably
        # why it's nt in the stdlib.
        # See: https://docs.python.org/2.7/reference/lexical_analysis.html#identifiers
        return re.match(r"^[_a-zA-Z][_a-zA-Z0-9]*$", text) is not None
