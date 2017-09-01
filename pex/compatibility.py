# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This file contains several 2.x/3.x compatibility checkstyle violations for a reason
# checkstyle: noqa

import os
from abc import ABCMeta
from io import BytesIO, StringIO
from numbers import Integral, Real
from sys import version_info as sys_version_info

try:
  # Python 2.x
  from ConfigParser import ConfigParser
except ImportError:
  # Python 3.x
  from configparser import ConfigParser

AbstractClass = ABCMeta('AbstractClass', (object,), {})
PY2 = sys_version_info[0] == 2
PY3 = sys_version_info[0] == 3

integer = (Integral,)
real = (Real,)
numeric = integer + real
string = (str,) if PY3 else (str, unicode)
unicode_string = (str,) if PY3 else (unicode,)
bytes = (bytes,)

if PY2:
  def to_bytes(st, encoding='utf-8'):
    if isinstance(st, unicode):
      return st.encode(encoding)
    elif isinstance(st, bytes):
      return st
    else:
      raise ValueError('Cannot convert %s to bytes' % type(st))

  def to_unicode(st, encoding='utf-8'):
    if isinstance(st, unicode):
      return st
    elif isinstance(st, (str, bytes)):
      return unicode(st, encoding)
    else:
      raise ValueError('Cannot convert %s to a unicode string' % type(st))
else:
  def to_bytes(st, encoding='utf-8'):
    if isinstance(st, str):
      return st.encode(encoding)
    elif isinstance(st, bytes):
      return st
    else:
      raise ValueError('Cannot convert %s to bytes.' % type(st))

  def to_unicode(st, encoding='utf-8'):
    if isinstance(st, str):
      return st
    elif isinstance(st, bytes):
      return str(st, encoding)
    else:
      raise ValueError('Cannot convert %s to a unicode string' % type(st))

_PY3_EXEC_FUNCTION = """
def exec_function(ast, globals_map):
  locals_map = globals_map
  exec ast in globals_map, locals_map
  return locals_map
"""

if PY3:
  def exec_function(ast, globals_map):
    locals_map = globals_map
    exec(ast, globals_map, locals_map)
    return locals_map
else:
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
  from contextlib import nested


if PY3:
  from urllib.request import pathname2url, url2pathname
else:
  from urllib import pathname2url, url2pathname


WINDOWS = os.name == 'nt'


__all__ = (
  'AbstractClass',
  'BytesIO',
  'ConfigParser',
  'PY2',
  'PY3',
  'StringIO',
  'WINDOWS',
  'bytes',
  'exec_function',
  'nested',
  'pathname2url',
  'string',
  'to_bytes',
  'url2pathname',
)
