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

from __future__ import print_function

import sys
import getpass
import types

from twitter.common.dirutil import safe_mkdir

import pkg_resources
from setuptools.package_index import PackageIndex

class QuietPackageIndex(PackageIndex):
  def __init__(self, index_url):
    PackageIndex.__init__(self, index_url)
    self.platform = None
    # It is necessary blow away local caches in order to not pick up stuff in site-packages.
    self._distmap = {}
    self._cache = {}

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
  REPOS = ('http://pypi.python.org/simple',)

  def __init__(self, repos=REPOS, cache=None):
    """
      Set up a Requirement fetcher.

      If repos specified, it should be a list of Cheesebox repositories or
      webservers exporting simple lists of Python .tar.gz/.egg packages.

      If cache is specified, override the default req fetching cache location.
    """
    self._pis = [QuietPackageIndex(url) for url in repos]
    self._cache = cache or ReqFetcher.DEFAULT_CACHE % {'user': getpass.getuser()}
    safe_mkdir(self._cache)

  def find(self, requirement, platform=pkg_resources.get_platform(), py_version=None):
    """
      Query the location of a distribution that fulfills a requirement.

      Returns a tuple of:
        location = the location of the distribution (or None if none found.)
        repo = the repo in which it was found (or None if local or not found.)
    """
    if py_version is None:
      py_version = '%s.%s' % (sys.version_info[0], sys.version_info[1])

    env = pkg_resources.Environment()
    if isinstance(requirement, str):
      requirement = pkg_resources.Requirement.parse(requirement)
    # first check the local cache
    for dist in pkg_resources.find_distributions(self._cache):
      if dist in requirement and env.can_add(dist):
        return (dist.location, None)
    # if nothing found, go out to remotes
    for repo in self._pis:
      repo.find_packages(requirement)
      for package in repo[requirement.project_name]:
        if pkg_resources.compatible_platforms(package.platform, platform):
          if package.py_version is not None and package.py_version != py_version:
            continue
          if package not in requirement:
            continue
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

