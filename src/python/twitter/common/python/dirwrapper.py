# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

import errno
import os
import zipfile


class DirWrapperHandle(object):
  class NotFoundError(Exception):
    pass

  def __init__(self, parent, source_file, dest_file, read_lambda):
    self._parent = parent
    self._source = source_file
    self._dest = dest_file
    self._read_lambda = read_lambda

  def parent(self):
    return self._parent

  def source(self):
    return self._source

  def dest(self):
    return self._dest

  def content(self):
    try:
      return self._read_lambda()
    except ProxyWrapper.Error:
      raise DirWrapperHandle.NotFoundError('File not found!')

  def __str__(self):
    return 'DirWrapperHandle(parent:%s, source:%s, dest:%s)' % (
      self._parent, self._source, self._dest)


class ProxyWrapper(object):
  class Error(Exception): pass
  class NotFoundError(Exception): pass

  def __init__(self, path):
    self._path = path

  def path(self):
    return self._path

  def listdir(self):
    raise NotImplementedError

  def read(self, name):
    return self.reader(name)()

  def reader(self, name):
    """
      Return a lambda that can read the item by the name of 'name'.
    """
    raise NotImplementedError

  def is_condensed(self):
    raise NotImplementedError


class ZipWrapper(ProxyWrapper):
  def __init__(self, path):
    super(ZipWrapper, self).__init__(path)
    try:
      self._zf = zipfile.ZipFile(path, 'r')
    except zipfile.BadZipfile:
      raise self.Error('Python environment %s is not a zip archive.' % path)

  def is_condensed(self):
    return True

  def listdir(self):
    for f in self._zf.namelist():
      if f.endswith('\\') or f.endswith('/'):
        # skip directory-like things
        continue
      yield f

  def reader(self, name):
    def read_data():
      try:
        return self._zf.read(name)
      except KeyError:
        raise self.NotFoundError(name)
    return read_data

  def handle(self, name):
    return DirWrapperHandle(os.path.basename(self._zf.fp.name), None, name, self.reader(name))


class DirWrapper(ProxyWrapper):
  def __init__(self, path):
    super(DirWrapper, self).__init__(path)
    self._dir = path

  def is_condensed(self):
    return False

  def listdir(self):
    for dir, dirs, files in os.walk(self._dir):
      for f in files:
        yield os.path.relpath(os.path.join(dir, f), self._dir)

  def reader(self, name):
    def read_data():
      try:
        with open(os.path.join(self._dir, name), 'rb') as fp:
          return fp.read()
      except IOError as e:
        if e.errno == errno.ENOENT:
          raise self.NotFoundError(name)
        else:
          raise
    return read_data

  def handle(self, name):
    return DirWrapperHandle(os.path.basename(self._dir), os.path.join(self._dir, name),
      name, self.reader(name))


class PythonDirectoryWrapper(object):
  """
    A wrapper to abstract methods to list/read files from PythonEnvironments whether they
    are files or directories.
  """
  class Error(Exception): pass
  class NotFoundError(Error): pass

  @classmethod
  def get(cls, path):
    try:
      if os.path.isdir(path):
        return DirWrapper(path)
      elif os.path.isfile(path):
        return ZipWrapper(path)
      else:
        raise cls.NotFoundError('Could not find path %s' % path)
    except ProxyWrapper.Error as e:
      raise cls.Error(str(e))
