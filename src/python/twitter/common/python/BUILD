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

python_library(
  name = "python",
  sources = rglobs('*.py'),
  dependencies = [
    python_requirement('distribute'),
    pants('src/python/twitter/common'),
  ],
  provides = setup_py(
    name = 'twitter.common.python',
    version = '0.0.0',
    description = "Twitter's Python interoperability libraries.",
    long_description = """
Twitter's Python interoperability libraries.  Includes support for package
fetching, building, installing, "distillation" into eggs, a recursive
zipimport implementation and Twitter's "PEX" standalone Python packaging
environment.
""",
    namespace_packages = [
      'twitter',
      'twitter.common'
    ]
  )
)

python_binary(
  name = 'distiller',
  source = 'distiller.py',
  dependencies = [
    pants('src/python/twitter/common/app'),
    pants('src/python/twitter/common/log'),
    pants(':python'),
  ]
)

python_binary(
  name = 'pex',
  entry_point = 'twitter.common.python.pex_builder:main',
  dependencies = [
    pants(':python')
  ]
)

page(name = 'pexreadme',
  source = 'README.md',
  dependencies = [
    pants(':pexinstall')
  ]
)

page(name = 'pexinstall',
  source = 'INSTALL.md',
)
