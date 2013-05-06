from __future__ import print_function

import sys
import tempfile

from .base import maybe_requirement_list
from .fetcher import PyPIFetcher
from .http import Crawler
from .obtainer import Obtainer
from .platforms import Platform
from .tracer import TRACER
from .translator import Translator

from pkg_resources import (
    find_distributions,
    Requirement,
    Environment,
    WorkingSet)


class ResolverEnvironment(Environment):
  def can_add(self, dist):
    return Platform.distribution_compatible(dist, python=self.python, platform=self.platform)


class Resolver(WorkingSet):
  def __init__(self, cache=None, crawler=None, fetchers=None, install_cache=None,
      conn_timeout=None):
    self._crawler = crawler or Crawler()
    self._fetchers = fetchers or [PyPIFetcher()]
    self._install_cache = install_cache
    self._cached_entries = set(find_distributions(cache)) if cache else set()
    self._entries = set()
    self._conn_timeout = conn_timeout
    super(Resolver, self).__init__(entries=[])

  def make_installer(self, python, platform):
    obtainer = Obtainer(self._crawler, self._fetchers,
        Translator.default(self._install_cache, python=python, platform=platform,
          conn_timeout=self._conn_timeout))
    return obtainer.obtain

  def resolve(self, requirements, python=Platform.python(), platform=Platform.current()):
    requirements = maybe_requirement_list(requirements)
    env = ResolverEnvironment([d.location for d in (self._entries | self._cached_entries)],
         python=python, platform=platform)
    added = set()
    for dist in super(Resolver, self).resolve(requirements, env=env,
        installer=self.make_installer(python, platform)):
      if dist not in self._entries:
        added.add(dist)
        self._entries.add(dist)
    return added

  def distributions(self):
    return self._entries
