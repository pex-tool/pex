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
    pants(':test_environment'),
    pants(':test_finders'),
    pants(':test_interpreter'),
    pants(':test_obtainer'),
    pants(':test_package'),
    pants(':test_pep425'),
    pants(':test_platform'),
    pants(':test_pex'),
    pants(':test_pex_builder'),
    pants(':test_util'),
  ]
)

python_tests(name = 'test_environment',
  sources = ['test_environment.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/python')
  ]
)

python_tests(name = 'test_finders',
  sources = ['test_finders.py'],
  dependencies = [
    pants('src/python/twitter/common/python'),
    python_requirement('mock', version_filter=lambda py, plat: py.startswith('2'))
  ]
)

python_tests(name = 'test_interpreter',
  sources = ['test_interpreter.py'],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants('src/python/twitter/common/python'),
  ]
)

python_tests(name = 'test_obtainer',
  sources = ['test_obtainer.py'],
  dependencies = [
    pants('src/python/twitter/common/python')
  ]
)

python_tests(name = 'test_package',
  sources = ['test_package.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/python'),
  ]
)

python_tests(name = 'test_pep425',
  sources = ['test_pep425.py'],
  dependencies = [
    pants('src/python/twitter/common/python'),
  ]
)

python_tests(name = 'test_platform',
  sources = ['test_platform.py'],
  dependencies = [
    pants('src/python/twitter/common/python')
  ]
)

python_tests(name = 'test_pex',
  sources = ['test_pex.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/python'),
  ]
)

python_tests(name = 'test_pex_builder',
  sources = ['test_pex_builder.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/python'),
  ]
)

python_tests(name = 'test_util',
  sources = ['test_util.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/python'),
    python_requirement('wheel'),
  ]
)
