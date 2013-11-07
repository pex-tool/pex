# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from abc import ABCMeta
from numbers import Integral, Real
from sys import version_info as sys_version_info

# TODO(wickman)  Since the io package is available in 2.6.x, use that instead of
# cStringIO/StringIO
try:
  # CPython 2.x
  from cStringIO import StringIO
except ImportError:
  try:
    # Python 2.x
    from StringIO import StringIO
  except:
    # Python 3.x
    from io import StringIO
    from io import BytesIO

AbstractClass = ABCMeta('AbstractClass', (object,), {})
PY2 = sys_version_info[0] == 2
PY3 = sys_version_info[0] == 3
StringIO = StringIO
BytesIO = BytesIO if PY3 else StringIO

integer = (Integral,)
real = (Real,)
numeric = integer + real
string = (str,) if PY3 else (str, unicode)
bytes = (bytes,)

if PY2:
  def to_bytes(st):
    return str(st)
else:
  def to_bytes(st):
    return bytes(st, encoding='utf8')

if PY3:
  def exec_function(ast, globals_map):
    locals_map = globals_map
    exec(ast, globals_map, locals_map)
    return locals_map
else:
  eval(compile(
"""
def exec_function(ast, globals_map):
  locals_map = globals_map
  exec ast in globals_map, locals_map
  return locals_map
""", "<exec_function>", "exec"))


__all__ = (
  'AbstractClass',
  'BytesIO',
  'PY2',
  'PY3',
  'StringIO',
  'bytes',
  'exec_function'
  'string',
  'to_bytes',
)
