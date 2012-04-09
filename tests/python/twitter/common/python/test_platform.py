# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

import pytest
from twitter.common.python.platforms import Platform

class TestPlatform(object):
  def test_pure_python(self):
    assert Platform.compatible(None, None)
    assert Platform.compatible(None, 'i386')
    assert Platform.compatible(None, 'universal')

  def test_unknown(self):
    with pytest.raises(Platform.UnknownPlatformError):
      Platform.compatible('macosx-10.0-morfgorf', 'macosx-10.1-morfgorf')
    with pytest.raises(Platform.UnknownPlatformError):
      Platform.compatible('macosx-10.0-x86_64', 'macosx-10.1-morfgorf')
    with pytest.raises(Platform.UnknownPlatformError):
      Platform.compatible('macosx-10.0-morfgorf', 'macosx-10.1-x86_64')

  def test_versioning(self):
    # Major versions incompatible
    assert not Platform.compatible('macosx-9.1-x86_64', 'macosx-10.0-x86_64')
    assert not Platform.compatible('macosx-10.0-x86_64', 'macosx-9.1-x86_64')

    # Platforms equal
    assert Platform.compatible('macosx-10.0-x86_64', 'macosx-10.0-x86_64')

    # Minor versions less than
    assert Platform.compatible('macosx-10.0-x86_64', 'macosx-10.1-x86_64')
    assert not Platform.compatible('macosx-10.1-x86_64', 'macosx-10.0-x86_64')
    assert Platform.compatible('macosx-10.9-x86_64', 'macosx-10.10-x86_64')
    assert not Platform.compatible('macosx-10.10-x86_64', 'macosx-10.9-x86_64')

  def test_platform_subsets(self):
    # Pure platform subset
    assert Platform.compatible('macosx-10.0-i386', 'macosx-10.0-intel')

    # Version and platform subset
    assert Platform.compatible('macosx-10.0-i386', 'macosx-10.1-intel')
    assert Platform.compatible('macosx-10.0-x86_64', 'macosx-10.1-intel')

    # Intersecting sets of platform but not pure subset
    assert Platform.compatible('macosx-10.0-fat', 'macosx-10.1-intel')

    # Non-intersecting sets of platform
    assert not Platform.compatible('macosx-10.0-ppc', 'macosx-10.1-intel')

    # Test our common case
    assert Platform.compatible('macosx-10.4-x86_64', 'macosx-10.7-intel')

  def test_cross_platform(self):
    assert not Platform.compatible('linux-x86_64', 'macosx-10.0-x86_64')

    # TODO(wickman): Should we do extended platform support beyond OS X?
    assert not Platform.compatible('linux-i386', 'linux-x86_64')
