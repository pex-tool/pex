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
    pants('tests/python/twitter/common/python/http:all'),
    pants(':test_nested'),
    pants(':test_obtainer'),
    pants(':test_platform'),
    pants(':test_pex_bootstrapper'),
    pants(':test_pex_builder_main'),
  ]
)

python_tests(name = 'test_nested',
  sources = ['test_nested.py'],
  dependencies = [
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/python')
  ]
)

python_tests(name = 'test_obtainer',
  sources = ['test_obtainer.py'],
  dependencies = [
    pants('src/python/twitter/common/python')
  ]
)

python_tests(name = 'test_platform',
  sources = ['test_platform.py'],
  dependencies = [
    pants('src/python/twitter/common/python')
  ]
)

python_tests(name = 'test_pex_bootstrapper',
  sources = ['test_pex_bootstrapper.py'],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants('src/python/twitter/common/python'),
  ]
)

python_tests(name = 'test_pex_builder_main',
  sources = ['test_pex_builder_main.py'],
  dependencies = [
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/common/python:pex')
  ]
)
