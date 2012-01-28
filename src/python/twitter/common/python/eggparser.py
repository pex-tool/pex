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

class EggParserOsModule:
  """
    Abstraction of the os-level functions the egg parser needs, so we can
    break it in tests.
  """
  @staticmethod
  def uname():
    import os
    return os.uname()

  @staticmethod
  def version_info():
    import sys
    return sys.version_info

class EggParser(object):
  """
  Parser of .egg filenames, which come in the following format:

  name ["-" version ["-py" pyver ["-" required_platform]]] "." ext
  """

  def __init__(self,
               uname = EggParserOsModule.uname(),
               version_info = EggParserOsModule.version_info()):
    self._uname = uname
    self._version_info = version_info

  @staticmethod
  def _get_egg_name(components):
    return (components[0], components[1:])

  @staticmethod
  def _get_egg_version(components):
    for k in range(len(components)):
      if components[k].startswith("py"):
        return ('-'.join(components[0:k]), components[k:])
    if components:
      return ('-'.join(components), [])
    else:
      return (None, [])

  @staticmethod
  def _get_egg_py_version(components):
    if components and components[0].startswith("py"):
      try:
        major, minor = components[0][2:].split('.')
        major, minor = int(major), int(minor)
        return ((major, minor), components[1:])
      except:
        pass
    return ((), components)

  @staticmethod
  def _get_egg_platform(components):
    return (tuple(components), [])

  def parse(self, filename):
    if not filename: return None
    if not filename.endswith('.egg'): return None
    components = filename[0:-len('.egg')].split('-')

    package_name, components = EggParser._get_egg_name(components)
    package_version, components = EggParser._get_egg_version(components)
    package_py_version, components = EggParser._get_egg_py_version(components)
    package_platform, components = EggParser._get_egg_platform(components)

    return (package_name, package_version, package_py_version, package_platform)

  def get_architecture(self):
    py_version = self._version_info[0:2]
    platform = self._uname[0].lower()
    arch = self._uname[-1].lower()
    if platform == 'darwin': platform = 'macosx'
    return (platform, arch, py_version)

  def is_compatible(self, filename):
    try:
      _, _, egg_py_version, egg_platform = self.parse(filename)
    except:
      return False
    my_platform, my_arch, my_py_version = self.get_architecture()
    if egg_py_version and egg_py_version != my_py_version: return False
    if egg_platform and egg_platform[0] != my_platform: return False
    # ignore specific architectures until we ever actually care.
    return True
