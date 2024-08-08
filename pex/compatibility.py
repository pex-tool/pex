# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This file contains several 2.x/3.x compatibility checkstyle violations for a reason
# checkstyle: noqa

from __future__ import absolute_import

import os
import re
import sys
import threading
from abc import ABCMeta
from sys import version_info as sys_version_info

from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import (
        IO,
        AnyStr,
        BinaryIO,
        Callable,
        Deque,
        List,
        Optional,
        Sequence,
        Text,
        Tuple,
        Type,
    )


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
text = cast("Type[Text]", str if PY3 else unicode)  # type: ignore[name-defined]


if PY2:
    from collections import Iterable as Iterable
    from collections import MutableSet as MutableSet
    from collections import deque
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


_PY2_EXEC_FUNCTION = """
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
    eval(compile(_PY2_EXEC_FUNCTION, "<exec_function>", "exec"))


if PY3:
    from http.client import HTTPConnection as HTTPConnection
    from http.client import HTTPResponse as HTTPResponse
    from urllib import parse as _url_parse
    from urllib.error import HTTPError as HTTPError
    from urllib.parse import quote as _url_quote
    from urllib.parse import unquote as _url_unquote
    from urllib.request import AbstractHTTPHandler as AbstractHTTPHandler
    from urllib.request import FileHandler as FileHandler
    from urllib.request import HTTPBasicAuthHandler as HTTPBasicAuthHandler
    from urllib.request import HTTPDigestAuthHandler as HTTPDigestAuthHandler
    from urllib.request import HTTPPasswordMgrWithDefaultRealm as HTTPPasswordMgrWithDefaultRealm
    from urllib.request import HTTPSHandler as HTTPSHandler
    from urllib.request import ProxyHandler as ProxyHandler
    from urllib.request import Request as Request
    from urllib.request import build_opener as build_opener
else:
    from urllib import quote as _url_quote
    from urllib import unquote as _url_unquote

    import urlparse as _url_parse
    from httplib import HTTPConnection as HTTPConnection
    from httplib import HTTPResponse as HTTPResponse
    from urllib2 import AbstractHTTPHandler as AbstractHTTPHandler
    from urllib2 import FileHandler as FileHandler
    from urllib2 import HTTPBasicAuthHandler as HTTPBasicAuthHandler
    from urllib2 import HTTPDigestAuthHandler as HTTPDigestAuthHandler
    from urllib2 import HTTPError as HTTPError
    from urllib2 import HTTPPasswordMgrWithDefaultRealm as HTTPPasswordMgrWithDefaultRealm
    from urllib2 import HTTPSHandler as HTTPSHandler
    from urllib2 import ProxyHandler as ProxyHandler
    from urllib2 import Request as Request
    from urllib2 import build_opener as build_opener

urlparse = _url_parse
url_unquote = _url_unquote
url_quote = _url_quote
del _url_parse, _url_unquote, _url_quote

if PY3:
    from queue import Queue as Queue

    # The `os.sched_getaffinity` function appears to be supported on Linux but not OSX.
    if not hasattr(os, "sched_getaffinity"):
        from os import cpu_count as cpu_count
    else:

        def cpu_count():
            # type: () -> Optional[int]
            # The set of CPUs accessible to the current process (pid 0).
            # N.B.: MyPy does not track the hasattr guard above under interpreters without the attr.
            cpu_set = os.sched_getaffinity(0)  # type: ignore[attr-defined]
            return len(cpu_set)

else:
    from multiprocessing import cpu_count as cpu_count

    from Queue import Queue as Queue

WINDOWS = os.name == "nt"


# Universal newlines is the default in Python 3.
MODE_READ_UNIVERSAL_NEWLINES = "rU" if PY2 else "r"


def _get_stdio_bytes_buffer(stdio):
    # type: (IO[str]) -> BinaryIO
    return cast("BinaryIO", getattr(stdio, "buffer", stdio))


def get_stdout_bytes_buffer():
    # type: () -> BinaryIO
    return _get_stdio_bytes_buffer(sys.stdout)


def get_stderr_bytes_buffer():
    # type: () -> BinaryIO
    return _get_stdio_bytes_buffer(sys.stderr)


if PY3:
    is_valid_python_identifier = str.isidentifier
else:

    def is_valid_python_identifier(text):
        # type: (str) -> bool

        # N.B.: Python 2.7 only supports ASCII characters so the check is easy and this is probably
        # why it's nt in the stdlib.
        # See: https://docs.python.org/2.7/reference/lexical_analysis.html#identifiers
        return re.match(r"^[_a-zA-Z][_a-zA-Z0-9]*$", text) is not None


if PY2:

    def indent(
        text,  # type: Text
        prefix,  # type: Text
        predicate=None,  # type: Optional[Callable[[Text], bool]]
    ):
        add_prefix = predicate if predicate else lambda line: bool(line.strip())
        return "".join(
            prefix + line if add_prefix(line) else line for line in text.splitlines(True)
        )

else:
    from textwrap import indent as indent


if PY3:
    from os.path import commonpath as commonpath
else:

    def commonpath(paths):
        # type: (Sequence[Text]) -> Text
        if not paths:
            raise ValueError("The paths given must be a non-empty sequence")
        if len(paths) == 1:
            return paths[0]
        if len({os.path.isabs(path) for path in paths}) > 1:
            raise ValueError(
                "Can't mix absolute and relative paths, given:\n{paths}".format(
                    paths="\n".join(paths)
                )
            )

        def components(path):
            # type: (Text) -> Iterable[Text]

            pieces = deque()  # type: Deque[Text]

            def append(piece):
                if piece and piece != ".":
                    pieces.appendleft(piece)

            head, tail = os.path.split(path)
            append(tail)
            while head:
                if "/" == head:
                    append(head)
                    break
                head, tail = os.path.split(head)
                append(tail)
            return pieces

        prefix = []  # type: List[Text]
        for atoms in zip(*(components(path) for path in paths)):
            if len(set(atoms)) == 1:
                prefix.append(atoms[0])
            else:
                break
        if not prefix:
            return ""
        return os.path.join(*prefix)


if PY3:
    from shlex import quote as _shlex_quote
else:
    from pipes import quote as _shlex_quote

shlex_quote = _shlex_quote


if PY3:

    def in_main_thread():
        # type: () -> bool
        return threading.current_thread() == threading.main_thread()

else:

    def in_main_thread():
        # type: () -> bool

        # Both CPython 2.7 and PyPy 2.7 do, in fact, have a threading._MainThread type that the
        # main thread derives from.
        return isinstance(
            threading.current_thread(),
            threading._MainThread,  # type: ignore[attr-defined]
        )
