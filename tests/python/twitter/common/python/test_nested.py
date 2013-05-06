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
import tempfile
import zipfile

from twitter.common.dirutil import safe_mkdir, safe_rmtree
from twitter.common.python.importer import Nested

class TestNested(object):
  def test_generate_prefixes(self):
    a, b, sep = 'a', 'b', os.sep
    assert list(Nested._generate_prefixes(sep)) == []
    assert list(Nested._generate_prefixes('')) == []
    assert list(Nested._generate_prefixes('.')) == []

    a_sep_b = a + sep + b
    assert list(Nested._generate_prefixes(a_sep_b)) == [a_sep_b, a]

    sep_a_sep_b = sep + a + sep + b
    assert list(Nested._generate_prefixes(sep_a_sep_b)) == [sep_a_sep_b, sep + a]

  def test_split_existing(self):
    td = tempfile.mkdtemp()
    try:
      assert Nested.split_existing(td) == (td, '.')
      assert Nested.split_existing(td + os.sep) == (td, '.')
      assert Nested.split_existing(os.path.join(td, 'a', 'b', 'c')) == (
        td, os.path.join('a', 'b', 'c'))
      assert Nested.split_existing(os.path.join(td, 'a', '..', 'c')) == (td, 'c')
    finally:
      safe_rmtree(td)
