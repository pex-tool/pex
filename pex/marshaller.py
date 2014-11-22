# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

try:
  from imp import get_magic
  HAS_MAGIC = True
except ImportError:
  HAS_MAGIC = False

import struct
import time

import marshal

from .compatibility import bytes as compatibility_bytes
from .compatibility import BytesIO


class CodeTimestamp(object):
  TIMESTAMP_RANGE = (4, 8)

  @classmethod
  def from_timestamp(cls, timestamp):
    return cls(timestamp)

  @classmethod
  def from_object(cls, pyc_object):
    stamp = time.localtime(
        struct.unpack('I', pyc_object[slice(*cls.TIMESTAMP_RANGE)])[0])
    return cls(stamp)

  def __init__(self, stamp=time.time()):
    self._stamp = stamp

  def to_object(self):
    return struct.pack('I', self._stamp)


class CodeMarshaller(object):
  class Error(Exception): pass
  class InvalidCode(Error): pass

  if HAS_MAGIC:
    MAGIC = struct.unpack('I', get_magic())[0]
  MAGIC_RANGE = (0, 4)
  TIMESTAMP_RANGE = (4, 8)

  @classmethod
  def from_pyc(cls, pyc):
    if not HAS_MAGIC:
      raise cls.InvalidCode('Interpreter cannot unmarshal .pyc!')
    if not isinstance(pyc, compatibility_bytes) and not hasattr(pyc, 'read'):
      raise cls.InvalidCode(
          "CodeMarshaller.from_pyc expects a code or file-like object!")
    if not isinstance(pyc, compatibility_bytes):
      pyc = pyc.read()
    pyc_magic = struct.unpack('I', pyc[slice(*cls.MAGIC_RANGE)])[0]
    if pyc_magic != cls.MAGIC:
      raise cls.InvalidCode("Bad magic number!  Got 0x%X" % pyc_magic)
    stamp = time.localtime(struct.unpack('I', pyc[slice(*cls.TIMESTAMP_RANGE)])[0])
    try:
      code = marshal.loads(pyc[8:])
    except ValueError as e:
      raise cls.InvalidCode("Unmarshaling error! %s" % e)
    return cls(code, stamp)

  @classmethod
  def from_py(cls, py, filename):
    stamp = int(time.time())
    code = compile(py.replace('\r\n', '\n').replace('\r', '\n'), filename, 'exec')
    return cls(code, stamp)

  def __init__(self, code, stamp):
    self._code = code
    self._stamp = stamp

  @property
  def code(self):
    return self._code

  def to_pyc(self):
    sio = BytesIO()
    sio.write(struct.pack('I', self.MAGIC))
    sio.write(struct.pack('I', self._stamp))
    sio.write(marshal.dumps(self._code))
    return sio.getvalue()
