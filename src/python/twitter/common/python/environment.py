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
import json

from twitter.common.dirutil.chroot import Chroot
from twitter.common.python.dependency import PythonDependency


"""
TODO(wickman)

Let's merge the PythonEnvironment and the PythonLauncher.  The logic between the
two classes is a little intertwined.  In reality, we want to be able to create
an environment and at any point in time call .fork() or .execute() on it, rather than
have to wrap it in a PythonLauncher object.

Similarly the only functionality that PexBuilder gives you is zipping up a chroot.
If we just abstract serialization/deserialization of a PythonEnvironment as being
a bunch of source/resource/dependency blobs, then we don't need things like magic
directories (.deps) to be a place to search for magic dependencies (.eggs).
"""

class PythonEnvironment(object):
  class InvalidDependency(Exception): pass
  class InvalidExecutableSpecification(Exception): pass
  DEPENDENCY_DIR = ".deps"
  MAIN = """
import os
import sys
from twitter.common.python import PythonLauncher

__entry_point__ = None
if locals().has_key('__file__') and __file__ is not None:
  __entry_point__ = os.path.dirname(__file__)
elif locals().has_key('__loader__'):
  from zipimport import zipimporter
  from pkgutil import ImpLoader
  if isinstance(__loader__, zipimporter):
    __entry_point__ = __loader__.archive
  elif isinstance(__loader__, ImpLoader):
    __entry_point__ = os.path.dirname(__loader__.get_filename())

if __entry_point__ is not None:
  PythonLauncher(__entry_point__).execute()
else:
  print >> sys.stderr, "Could not launch Python executable!"
  sys.exit(2)
"""

  def __init__(self, path):
    self._chroot = Chroot(path)

  def chroot(self):
    return self._chroot

  def path(self):
    return self.chroot().path()

  def add_source(self, filename, env_filename):
    self._chroot.link(filename, env_filename, "source")

  def add_resource(self, filename, env_filename):
    self._chroot.link(filename, env_filename, "resource")

  def add_dependency(self, dependency):
    added_files = set()
    if not isinstance(dependency, PythonDependency):
      raise PythonEnvironment.InvalidDependency(
        "Input dependency (%s) is not a valid PythonDependency!" % repr(dependency))
    for fn, content in dependency.files():
      added_files.add(os.path.join(self.path(), PythonEnvironment.DEPENDENCY_DIR, fn))
      self._chroot.write(content, os.path.join(PythonEnvironment.DEPENDENCY_DIR, fn), "dependency")
    return (os.path.join(self.path(), PythonEnvironment.DEPENDENCY_DIR), added_files)

  def add_dependency_file(self, filename, dep_filename):
    self._chroot.link(filename, os.path.join(PythonEnvironment.DEPENDENCY_DIR, dep_filename),
        "dependency")

  def set_executable(self, filename, env_filename=None):
    if env_filename is None:
      env_filename = os.path.basename(filename)
    self._chroot.link(filename, env_filename, "executable")

  def executable(self):
    """
      Return the executable target of this environment if one is specified.  If not
      specified, return None.
    """
    exe = self._chroot.get("executable")
    if len(exe) > 1:
      raise PythonEnvironment.InvalidExecutableSpecification(
        "Expected one or zero executables, but instead got executables = %s" % repr(exe))
    if len(exe) == 1:
      return exe.copy().pop()

  def _prepare_inits(self):
    relative_digest = self._chroot.get("source")
    init_digest = set()
    for path in relative_digest:
      split_path = path.split(os.path.sep)
      for k in range(1, len(split_path)):
        sub_path = os.path.sep.join(split_path[0:k] + ['__init__.py'])
        if sub_path not in relative_digest and sub_path not in init_digest:
          self._chroot.touch(sub_path)
          init_digest.add(sub_path)

  def _script(self):
    """
      Returns the module-form of the entry point or None if it's not there.
    """
    if self.executable():
      source = self.executable()
      source.replace(os.path.sep, '.')
      source = source.rpartition('.')[0]
      return source

  def _manifest(self):
    manifest = {}
    script = self._script()
    if script:
      manifest.update({'entry': script})
    return json.dumps(manifest)

  def _prepare_manifest(self):
    self._chroot.write(self._manifest(), 'PEX-INFO', label='manifest')

  def _prepare_main(self):
    self._chroot.write(self.MAIN, '__main__.py', label='main')

  def freeze(self):
    self._prepare_inits()
    self._prepare_manifest()
    self._prepare_main()
