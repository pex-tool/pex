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
import errno
import hashlib
import getpass

from twitter.common.dirutil import safe_mkdir, safe_open
from twitter.common.python.eggparser import EggParser

class EggCache(object):
  DEFAULT_PATH = "/var/tmp/%(user)s"
  PATH_FORMAT = "%(name)s.%(crc)s"

  def __init__(self, pexfile, basepath=None):
    self._pex = pexfile
    self._name = os.path.basename(self._pex.path())
    if self._pex.is_condensed():
      self._cache_path = basepath if basepath is not None else EggCache.DEFAULT_PATH
      self._cache_path = os.path.join(self._cache_path, EggCache.PATH_FORMAT) % {
        'user': getpass.getuser(),
        'name': self._name,
        'crc': hashlib.md5(open(self._pex.path(), 'rb').read()).hexdigest()
      }
    else:
      self._cache_path = self._pex.path()
    self._eggparser = EggParser()
    self._registry = set()
    self._populate_registry()

  def _populate_registry(self):
    def extract_usable_egg(filename):
      if not filename.startswith('.deps/'):
        return None
      spath = filename.split('/')
      if len(spath) >= 2:
        if self._eggparser.is_compatible(spath[1]):
          return '/'.join(spath[0:2])
      return None

    for name in self._pex.listdir():
      extracted = extract_usable_egg(name)
      if extracted:
        self._registry.add(extracted)

  def paths(self):
    """
      Return valid sys.path components for this egg, dumping them to a local
      cache if necessary.
    """
    def same(filename, contents):
      if not os.path.exists(filename):
        return False
      # Hmm...for directories we should probably recursively verify
      if not os.path.isfile(filename):
        return True
      with open(filename, 'rb') as fp:
        file_contents = fp.read()
      return hashlib.md5(file_contents).digest() == hashlib.md5(contents).digest()

    def populate_cache():
      safe_mkdir(self._cache_path)

      for fn in self._pex.listdir():
        egg_prefix = '/'.join(fn.split('/')[0:2])
        if egg_prefix in self._registry:
          fn_contents = self._pex.read(fn)
          dest = os.path.join(self._cache_path, fn)
          if same(dest, fn_contents):
            continue
          with safe_open(dest, 'wb') as fn_out:
            fn_out.write(fn_contents)

    if self._pex.is_condensed():
      populate_cache()

    path_adjuncts = []
    for egg in self._registry:
      path_adjuncts.append(os.path.join(self._cache_path, egg))

    return path_adjuncts
