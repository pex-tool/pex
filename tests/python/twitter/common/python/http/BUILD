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

python_test_suite(name = 'all',
  dependencies = [
    pants(':test_crawler'),
    pants(':test_http'),
    pants(':test_link'),
  ]
)

python_library(name = 'test_base',
  sources = ['base.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil')
  ]
)

python_tests(name = 'test_crawler',
  sources = ['test_crawler.py'],
  dependencies = [
    pants(':test_base'),
    pants('src/python/twitter/common/python')
  ]
)

python_tests(name = 'test_http',
  sources = ['test_http.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/common/quantity'),
    pants('src/python/twitter/common/testing'),
    pants('3rdparty/python:mox')
  ]
)

python_tests(name = 'test_link',
  sources = ['test_link.py'],
  dependencies = [
    pants(':test_base'),
    pants('src/python/twitter/common/python')
  ]
)
