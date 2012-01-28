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

from twitter.common.python.dirwrapper import PythonDirectoryWrapper
from twitter.common.python.reqbuilder import ReqBuilder

from setuptools.package_index import EXTENSIONS as VALID_SOURCE_EXTENSIONS

"""
TODO(wickman):  I don't like how this is factored right now, though it's an
improvement over what we used to have.

In the next iteration let's do:

Make PythonDependency a base class for:
  PythonEggDependency <= .egg(s)
  PythonTgzDependency <= .tgz
  PythonReqDependency <= pkg_resources.Requirement

PythonDependency exports the API:
   input_files()
   activate(path) (idempotent) => .egg heads

We then encode PythonDependency blobs directly into the manifest to make the
dependencies more explicit than just autodetecting a bunch of ".egg" directories
in the "dependency" fileset of the chroot.
"""

class PythonDependency(object):
  class UnpackingError(Exception): pass
  class NotFoundError(Exception): pass
  class BuildError(Exception): pass
  class RequirementError(Exception): pass

  DEFAULT_URI = "http://pypi.python.org"

  @staticmethod
  def from_file(filename):
    if filename.lower().endswith('.egg'):
      return PythonDependency.from_egg(filename)
    else:
      for suffix in VALID_SOURCE_EXTENSIONS:
        if filename.lower().endswith(suffix):
          return PythonDependency.from_source(filename)
    raise PythonDependency.RequirementError(
      'Unrecognized Python dependency file format: %s!' % filename)

  # TODO(wickman): This arguably shouldn't belong -- we should probably
  #  have the bootstrapper interface with ReqFetcher so that
  #  install_requirements never goes out to the network w/o our knowledge.
  @staticmethod
  def from_req(requirement):
    dists = ReqBuilder.install_requirement(requirement)
    return PythonDependency.from_distributions(*list(dists))

  @staticmethod
  def from_source(filename):
    if not os.path.exists(filename):
      raise PythonDependency.NotFoundError(
        "Could not find PythonDependency target %s!" % filename)
    dists = ReqBuilder.install_requirement(filename)
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
    if not isinstance(eggheads, (types.ListType, types.TupleType)):
      raise ValueError('Expected eggs to be a list of filenames!  Got %s' % type(eggheads))
    self._eggs = {}
    for egg in eggheads:
      self._eggs[os.path.basename(egg)] = PythonDirectoryWrapper.get(egg)

  def files(self):
    """
      Iterator that yields
        (filename, content)

      Where filename is going to be:
        my_egg.egg if a file egg
        my_egg.egg/EGG-INFO/stuff1.txt if a directory egg or unzipsafe egg
    """
    for egg, wrapper in self._eggs.iteritems():
      all_files = sorted(wrapper.listdir())
      if 'EGG-INFO/zip-safe' in all_files and wrapper.is_condensed():
        with open(wrapper.path(), 'r') as fp:
          yield (egg, fp.read())
      else:
        for filename in all_files:
          # do space optimization where we skip .pyc/.pyo if the .py is already included
          if (filename.endswith('.pyc') or filename.endswith('.pyo')) and (
              '%s.py' % filename[:-4] in all_files):
            continue
          yield (os.path.join(egg, filename), wrapper.read(filename))
