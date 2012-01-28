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

import unittest
from twitter.common.python.eggparser import EggParser

class EggParserTestHelper:
  @staticmethod
  def _construct_parser_with(output_uname, output_version):
    return EggParser(uname=output_uname, version_info=output_version)

  @staticmethod
  def _get_platform(platform, arch='i386', major=2, min=6):
    uname = (platform, None, None, None, arch)
    version = (major, min, 0, None, 0)
    return EggParserTestHelper._construct_parser_with(uname, version)

  @staticmethod
  def get_darwin_platform(arch='i386', major=2, min=6):
    return EggParserTestHelper._get_platform('Darwin', arch, major, min)

  @staticmethod
  def get_linux_platform(arch='i386', major=2, min=6):
    return EggParserTestHelper._get_platform('Linux', arch, major, min)

class EggParserTest(unittest.TestCase):
  GOOD_EGGS = [
   "Mako-0.4.0-py2.6.egg",
   "Thrift-0.7.0_dev-py2.6.egg",
   "ZooKeeper-0.4-py2.6-linux-x86_64.egg",
   "ZooKeeper-0.4-py2.6-macosx-10.6-x86_64.egg",
   "antlr_python_runtime-3.1.3-py2.6.egg",
   "setuptools-0.6c11-py2.6.egg",
   "endpoint-dev-py2.6.egg",
   "endpoint.egg"
  ]

  BAD_EGGS = [
   "Mako-0.py2.6.egg",
   "py2.6.egg",
   ".egg",
   "",
   None,
   "ZooKeeper-py2.6-linux-x86_64.egg",
   "ZooKeeper-macosx-10.6-x86_64.egg",
   "elfowl-pyver-py2.6.egg",
  ]

  ARCH_INSPECIFIC = [
   "Mako-0.4.0-py2.6.egg",
   "Thrift-0.7.0_dev-py2.6.egg",
   "antlr_python_runtime-3.1.3-py2.6.egg",
   "setuptools-0.6c11-py2.6.egg",
   "endpoint-dev-py2.6.egg",
  ]

  DARWIN_SPECIFIC = [
   "ZooKeeper-0.4-py2.6-macosx-10.6-x86_64.egg",
  ]

  LINUX_SPECIFIC = [
   "ZooKeeper-0.4-py2.6-linux-x86_64.egg",
  ]

  def setUp(self):
    self.parser = EggParser()

  def test_parser(self):
    for egg in EggParserTest.GOOD_EGGS + EggParserTest.BAD_EGGS:
      try:
        self.parser.parse(egg)
      except:
        self.fail("Failed to parse valid Egg: %s" % egg)

  def test_darwin_arch(self):
    parser = EggParserTestHelper.get_darwin_platform()
    arch = parser.get_architecture()
    self.assertEquals(arch[0], 'macosx')

  def test_darwin_compatibility(self):
    parser = EggParserTestHelper.get_darwin_platform()
    for egg in EggParserTest.DARWIN_SPECIFIC + EggParserTest.ARCH_INSPECIFIC:
      self.assertTrue(parser.is_compatible(egg))
    for egg in EggParserTest.LINUX_SPECIFIC:
      self.assertFalse(parser.is_compatible(egg))

  def test_linux_arch(self):
    parser = EggParserTestHelper.get_linux_platform()
    arch = parser.get_architecture()
    self.assertEquals(arch[0], 'linux')

  def test_linux_compatibility(self):
    parser = EggParserTestHelper.get_linux_platform()
    for egg in EggParserTest.LINUX_SPECIFIC + EggParserTest.ARCH_INSPECIFIC:
      self.assertTrue(parser.is_compatible(egg))
    for egg in EggParserTest.DARWIN_SPECIFIC:
      self.assertFalse(parser.is_compatible(egg))

  def test_name_extraction(self):
    name, _, _, _ = self.parser.parse("Mako.egg")
    self.assertEquals(name, "Mako")
    name, _, _, _ = self.parser.parse("Thrift-0.7.0_dev.egg")
    self.assertEquals(name, "Thrift")
    name, _, _, _ = self.parser.parse("Bonkers-0.7.0-py2.6.egg")
    self.assertEquals(name, "Bonkers")
    name, _, _, _ = self.parser.parse("ZooKeeper-0.4-py2.6-linux-x86_64.egg")
    self.assertEquals(name, "ZooKeeper")

  def test_version_extraction(self):
    _, version, _, _ = self.parser.parse("Mako.egg")
    self.assertEquals(version, None)
    _, version, _, _ = self.parser.parse("Thrift-0.7.0_dev.egg")
    self.assertEquals(version, "0.7.0_dev")
    _, version, _, _ = self.parser.parse("Bonkers-0.7.0-py2.6.egg")
    self.assertEquals(version, "0.7.0")
    _, version, _, _ = self.parser.parse("ZooKeeper-0.4-py2.6-linux-x86_64.egg")
    self.assertEquals(version, "0.4")

  def test_py_version_extraction(self):
    _, _, py_version, _ = self.parser.parse("Mako.egg")
    self.assertEquals(py_version, ())
    _, _, py_version, _ = self.parser.parse("Thrift-0.7.0_dev.egg")
    self.assertEquals(py_version, ())
    _, _, py_version, _ = self.parser.parse("Bonkers-0.7.0-py2.6.egg")
    self.assertEquals(py_version, (2,6))
    _, _, py_version, _ = self.parser.parse("ZooKeeper-0.4-py2.6-linux-x86_64.egg")
    self.assertEquals(py_version, (2,6))

  def test_platform_extraction(self):
    _, _, _, platform = self.parser.parse("Mako.egg")
    self.assertEquals(platform, ())
    _, _, _, platform = self.parser.parse("Thrift-0.7.0_dev.egg")
    self.assertEquals(platform, ())
    _, _, _, platform = self.parser.parse("Bonkers-0.7.0-py2.6.egg")
    self.assertEquals(platform, ())
    _, _, _, platform = self.parser.parse("ZooKeeper-0.4-py2.6-linux-x86_64.egg")
    self.assertEquals(platform, ('linux', 'x86_64'))
    _, _, _, platform = self.parser.parse("ZooKeeper-0.4-py2.6-linux-1-2-3-x86_64.egg")
    self.assertEquals(platform, ('linux', '1', '2', '3', 'x86_64'))
    _, _, _, platform = self.parser.parse("ZooKeeper-0.4-py2.6-macosx-10.6-i386.egg")
    self.assertEquals(platform, ('macosx', '10.6', 'i386'))
