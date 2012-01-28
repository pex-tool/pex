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

import os
import zipfile

class _ProxyWrapper(object):
  def __init__(self, path):
    self._path = path

  def path(self):
    return self._path

  def listdir(self):
    raise NotImplementedError

  def read(self, name):
    raise NotImplementedError

  def is_condensed(self):
    raise NotImplementedError

class _ZipWrapper(_ProxyWrapper):
  def __init__(self, path):
    _ProxyWrapper.__init__(self, path)
    try:
      self._zf = zipfile.ZipFile(path, 'r')
    except zipfile.BadZipfile:
      raise ValueError('Python environment %s is not a zip archive.' % path)

  def is_condensed(self):
    return True

  def listdir(self):
    for f in self._zf.namelist():
      if f.endswith('\\') or f.endswith('/'):
        # skip directory-like things
        continue
      yield f

  def read(self, name):
    return self._zf.read(name)

class _DirWrapper(_ProxyWrapper):
  def __init__(self, path):
    _ProxyWrapper.__init__(self, path)
    self._dir = path

  def is_condensed(self):
    return False

  def listdir(self):
    for dir, dirs, files in os.walk(self._dir):
      for f in files:
        yield os.path.relpath(os.path.join(dir, f), self._dir)

  def read(self, name):
    with open(os.path.join(self._dir, name), 'r') as fp:
      return fp.read()

class PythonDirectoryWrapper:
  """
    A wrapper to abstract methods to list/read files from PythonEnvironments whether they
    are files or directories.
  """
  @staticmethod
  def get(path):
    if os.path.isdir(path):
      return _DirWrapper(path)
    elif os.path.isfile(path):
      return _ZipWrapper(path)
