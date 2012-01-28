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

import types
import getpass

from twitter.common.dirutil import safe_mkdir

import pkg_resources
from setuptools.package_index import PackageIndex

class QuietPackageIndex(PackageIndex):
  def __init__(self, index_url):
    PackageIndex.__init__(self, index_url)
    self.platform = None

  def devnull(self, msg, *args):
    pass

  info = warn = debug = devnull

class ReqFetcher(object):
  """
    Wrapper around setuptools.PackageIndex for more conveniently manipulating
    multi-platform distributions from multiple layers of repositories/caches.
  """

  class InternalError(Exception): pass

  DEFAULT_CACHE = "/var/tmp/%(user)s/.cache"

  # This should be externally configurable.
  REPOS = [
    'http://127.0.0.1:8000',
    'https://svn.twitter.biz/science-binaries',
    'http://pypi.python.org/simple'
  ]

  def __init__(self, repos=[], cache=None):
    """
      Set up a Requirement fetcher.

      If repos specified, it should be a list of Cheesebox repositories or
      webservers exporting simple lists of Python .tar.gz/.egg packages.

      If cache is specified, override the default req fetching cache location.
    """
    self._repos = repos or ReqFetcher.REPOS
    # Too bad there is no iterable() function like there is callable().
    if not hasattr(self._repos, '__iter__'):
      raise TypeError('repos should be an iterable type!  got %s' % repr(self._repos))
    self._pis = [QuietPackageIndex(url) for url in self._repos]
    self._cache = cache or ReqFetcher.DEFAULT_CACHE % {'user': getpass.getuser()}
    safe_mkdir(self._cache)

  def find(self, requirement, platform=pkg_resources.get_platform()):
    """
      Query the location of a distribution that fulfills a requirement.

      Returns a tuple of:
        location = the location of the distribution (or None if none found.)
        repo = the repo in which it was found (or None if local or not found.)
    """
    if isinstance(requirement, str):
      requirement = pkg_resources.Requirement.parse(requirement)
    # first check the local cache
    for dist in pkg_resources.find_distributions(self._cache):
      if dist in requirement and pkg_resources.compatible_platforms(dist.platform, platform):
        return (dist.location, None)
    # if nothing found, go out to remotes
    for repo in self._pis:
      repo.find_packages(requirement)
      for package in repo[requirement.project_name]:
        if pkg_resources.compatible_platforms(package.platform, platform):
          return (package.location, repo)
    return (None, None)

  def fetch(self, requirement, platform=pkg_resources.get_platform()):
    """
      Fetch a distribution that matches the requirement.

      Returns a local path to the distribution or None if nothing
      appropriate found.
    """
    location, repo = self.find(requirement, platform)
    if repo:
      return repo.download(location, self._cache)
    # if location is set and repo is None, it's a local package.
    elif location:
      return location

