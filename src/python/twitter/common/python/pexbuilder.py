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
from twitter.common.dirutil import chmod_plus_x
from twitter.common.python.environment import PythonEnvironment

class PexBuilder(object):
  def __init__(self, environment):
    if not isinstance(environment, PythonEnvironment):
      raise ValueError('Expected environment to be of type PythonEnvironment!  Got %s' % (
        type(environment)))
    self._env = environment

  def write(self, filename):
    chroot = self._env.chroot().dup()
    chroot.zip(filename + '~')
    with open(filename, "w") as pexfile:
      pexfile.write('#!/usr/bin/env python2.6\n')
      with open(filename + '~') as pexfile_zip:
        pexfile.write(pexfile_zip.read())
    chroot.delete()
    os.unlink(filename + '~')
    chmod_plus_x(filename)
