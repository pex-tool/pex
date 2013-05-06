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

from twitter.common.python.fetcher import Fetcher
from twitter.common.python.http import EggLink, SourceLink
from twitter.common.python.obtainer import Obtainer
from pkg_resources import Requirement


def test_link_preference():
  sl = SourceLink('psutil-0.6.1.tar.gz')
  el = EggLink('psutil-0.6.1.egg')
  assert Obtainer.link_preference(el) > Obtainer.link_preference(sl)


class FakeObtainer(Obtainer):
  def __init__(self, links):
    self._links = list(links)

  def iter_unordered(self, req):
    return self._links


class FakeCrawler(object):
  def __init__(self, hrefs):
    self._hrefs = hrefs
    self.opener = None

  def crawl(self, *args, **kw):
    return self._hrefs


def test_iter_ordering():
  PS, PS_EGG = SourceLink('psutil-0.6.1.tar.gz'), EggLink('psutil-0.6.1-linux-x86_64.egg')
  PS_REQ = Requirement.parse('psutil')

  assert list(FakeObtainer([PS, PS_EGG]).iter(PS_REQ)) == [PS_EGG, PS]
  assert list(FakeObtainer([PS_EGG, PS]).iter(PS_REQ)) == [PS_EGG, PS]


def test_href_translation():
  VERSIONS = ['0.4.0', '0.4.1', '0.5.0', '0.6.0']
  def fake_link(version):
    return 'http://www.example.com/foo/bar/psutil-%s.tar.gz' % version
  fc = FakeCrawler(map(fake_link, VERSIONS))
  ob = Obtainer(fc, [], [])

  for v in VERSIONS:
    pkgs = list(ob.iter(Requirement.parse('psutil==%s' % v)))
    assert len(pkgs) == 1
    assert pkgs[0] == SourceLink(fake_link(v))

  assert list(ob.iter(Requirement.parse('psutil>=0.5.0'))) == [
    SourceLink(fake_link('0.6.0')),
    SourceLink(fake_link('0.5.0'))]

  assert list(ob.iter(Requirement.parse('psutil'))) == map(SourceLink,
      map(fake_link, reversed(VERSIONS)))
