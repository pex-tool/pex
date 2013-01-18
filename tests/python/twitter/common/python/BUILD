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


python_test_suite(name = 'python',
  dependencies = [
    ':test_nested',
    ':test_platform',
  ]
)

python_tests(name = 'test_nested',
  sources = ['test_nested.py'],
  dependencies = [
    'src/python/twitter/common/python'
  ]
)

python_tests(name = 'test_platform',
  sources = ['test_platform.py'],
  dependencies = [
    'src/python/twitter/common/python'
  ]
)
