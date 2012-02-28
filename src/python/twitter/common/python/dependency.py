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
import types
import zipfile
from collections import Sequence

from twitter.common.lang import Compatibility
from twitter.common.python.dirwrapper import PythonDirectoryWrapper, DirWrapperHandle
from twitter.common.python.interpreter import PythonInterpreter
from twitter.common.python.reqbuilder import ReqBuilder

from setuptools.package_index import EXTENSIONS as VALID_SOURCE_EXTENSIONS

"""
  N.B. from pkg_resources.PathMetadata

  # Unpacked egg directories:
  egg_path = "/path/to/PackageName-ver-pyver-etc.egg"
  metadata = PathMetadata(egg_path, os.path.join(egg_path,'EGG-INFO'))
  dist = Distribution.from_filename(egg_path, metadata=metadata)

  # Zipped eggs:
  egg_importer = zipimport.zipimporter(egg_path)
  metadata = EggMetadata(egg_importer)
  dist = Distribution.from_filename(egg_path, metadata=metadata)
"""

class PythonDependency(object):
  class UnpackingError(Exception): pass
  class NotFoundError(Exception): pass
  class BuildError(Exception): pass
  class RequirementError(Exception): pass

  @staticmethod
  def from_file(filename, interpreter=PythonInterpreter.get()):
    if filename.lower().endswith('.egg'):
      return PythonDependency.from_eggs(filename, interpreter=interpreter)
    else:
      for suffix in VALID_SOURCE_EXTENSIONS:
        if filename.lower().endswith(suffix):
          return PythonDependency.from_source(filename, interpreter=interpreter)
    raise PythonDependency.RequirementError(
      'Unrecognized Python dependency file format: %s!' % filename)

  @staticmethod
  def from_req(requirement, interpreter=PythonInterpreter.get(), **kw):
    dists = ReqBuilder.install_requirement(requirement, interpreter=interpreter, **kw)
    return PythonDependency.from_distributions(*list(dists))

  @staticmethod
  def from_source(filename, interpreter=PythonInterpreter.get(), **kw):
    if not os.path.exists(filename):
      raise PythonDependency.NotFoundError(
        "Could not find PythonDependency target %s!" % filename)
    dists = ReqBuilder.install_requirement(filename, interpreter=interpreter, **kw)
    return PythonDependency.from_distributions(*list(dists))

  @staticmethod
  def from_distributions(*distributions):
    if not distributions:
      raise PythonDependency.BuildError(
        "Cannot extract PythonDependency from empty distribution!")
    else:
      if any(not dist.location.endswith('.egg') for dist in distributions):
        raise PythonDependency.RequirementError(
          'PythonDependency.from_distribution requires Egg distributions!')
      return PythonDependency.from_eggs(*[dist.location for dist in distributions])

  @staticmethod
  def from_eggs(*egg_paths):
    return PythonDependency(egg_paths)

  def __init__(self, eggheads):
    """
      eggheads = List of files or directories that end with ".egg" and point to
        valid eggs.

      Not intended to be called directly.  Instead use the from_* factory methods.
    """
    if not isinstance(eggheads, Sequence) or isinstance(eggheads, Compatibility.string):
      raise ValueError('Expected eggs to be a list of filenames!  Got %s' % type(eggheads))
    self._eggs = {}
    for egg in eggheads:
      self._eggs[os.path.basename(egg)] = PythonDirectoryWrapper.get(egg)

  def __str__(self):
    return 'PythonDependency(eggs: %s)' % (' '.join(self._eggs.keys()))

  def size(self):
    return len(self._eggs)

  def files(self):
    """
      Iterator that yields
        (filename, content)

      Where filename is going to be:
        my_egg.egg if a file egg
        my_egg.egg/EGG-INFO/stuff1.txt if a directory egg or unzipsafe egg
    """
    for egg, wrapper in self._eggs.items():
      all_files = sorted(wrapper.listdir())
      if 'EGG-INFO/zip-safe' in all_files and wrapper.is_condensed():
        def read_contents():
          with open(wrapper.path(), 'rb') as fp:
            return fp.read()
        yield DirWrapperHandle('', wrapper.path(), egg, read_contents)
      else:
        for filename in all_files:
          # do space optimization where we skip .pyc/.pyo if the .py is already included
          if (filename.endswith('.pyc') or filename.endswith('.pyo')) and (
              '%s.py' % filename[:-4] in all_files):
            continue
          yield wrapper.handle(filename)
