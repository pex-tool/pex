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

# TODO(John Sirois): This works around a bug in namespace package injection for the setup_py
# command's sdist generation of a library using with_binaries.  In this case
# the src/python/twitter/common/python target has a with_binaries that includes the pex.pex pex and
# this __init__.py is emitted in the sdist with no namespace package by the setup_py command unless
# manually added below.
__import__('pkg_resources').declare_namespace(__name__)
