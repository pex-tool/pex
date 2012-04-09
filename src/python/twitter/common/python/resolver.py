from __future__ import print_function

import contextlib
import sys
import time
from types import GeneratorType

from pkg_resources import (
  find_distributions,
  Distribution,
  DistributionNotFound,
  EggMetadata,
  Environment,
  Requirement,
  WorkingSet)

from twitter.common.collections import OrderedSet
from twitter.common.python.distiller import Distiller
from twitter.common.python.installer import Installer
from twitter.common.python.importer import EggZipImporter
from twitter.common.python.platforms import Platform


class RequirementWrapper(object):
  @staticmethod
  def get(req):
    if isinstance(req, Requirement):
      return req
    return Requirement.parse(req)


class Resolver(Environment):
  """
    Resolve a series of requirements.

    Simplest use-case (cache-less)
      >>> from twitter.common.python.resolver import Resolver
      >>> from twitter.common.python.fetcher import Fetcher
      >>> pypi = Fetcher.pypi()
      >>> resolver = Resolver(fetcher = pypi)
      Calling environment super => 0.045ms
      >>> resolver.resolve('mako')
      Fetching mako => 6691.651ms
      Building mako => 557.141ms
      Fetching MarkupSafe>=0.9.2 => 3314.960ms
      Building MarkupSafe>=0.9.2 => 542.930ms
      Resolving mako => 11110.769ms
      [Mako 0.6.2 (/private/var/folders/Uh/UhXpeRIeFfGF7HoogOKC+++++TI/-Tmp-/tmplyR5kH/lib/python2.6/site-packages),
       MarkupSafe 0.15 (/private/var/folders/Uh/UhXpeRIeFfGF7HoogOKC+++++TI/-Tmp-/tmptUWECl/lib/python2.6/site-packages)]

    With an install cache:
      >>> resolver = Resolver(fetcher = pypi,
      ...                     caches = [os.path.expanduser('~/.pex/install')],
      ...                     install_cache = os.path.expanduser('~/.pex/install'))

    First invocation:
      >>> resolver.resolve('mako')
      Activating cache /Users/wickman/.pex/install-new => 6.091ms
      ...
      Resolving mako => 3693.405ms
      [Mako 0.6.2 (/Users/wickman/.pex/install-new/Mako-0.6.2-py2.6.egg),
       MarkupSafe 0.15 (/Users/wickman/.pex/install-new/MarkupSafe-0.15-py2.6-macosx-10.4-x86_64.egg)]

    Second invocation (distilled and memoized in the cache):
      >>> resolver.resolve('mako')
      Resolving mako => 1.813ms
      [Mako 0.6.2 (/Users/wickman/.pex/install-new/Mako-0.6.2-py2.6.egg),
       MarkupSafe 0.15 (/Users/wickman/.pex/install-new/MarkupSafe-0.15-py2.6-macosx-10.4-x86_64.egg)]
  """

  class Subcache(object):
    def __init__(self, path, env):
      self._activated = False
      self._path = path
      self._env = env

    @property
    def activated(self):
      return self._activated

    def activate(self):
      if not self._activated:
        with self._env.timed('Activating cache %s' % self._path):
          for dist in find_distributions(self._path):
            if self._env.can_add(dist):
              self._env.add(dist)
        self._activated = True

  @classmethod
  @contextlib.contextmanager
  def timed(cls, prefix):
    start_time = time.time()
    yield
    cls._log('%s => %.3fms' % (prefix, 1000.0 * (time.time() - start_time)))

  @classmethod
  def _log(cls, msg, *args, **kw):
    print(msg, *args, **kw)

  def __init__(self,
               caches=(),
               install_cache=None,
               fetcher=None,
               fetcher_provider=None,
               platform=Platform.current(),
               python=sys.version[:3]):
    assert (fetcher is not None) + (fetcher_provider is not None) == 1, (
      "At most one of fetcher or fetcher_provider should be supplied")
    self._subcaches = [Resolver.Subcache(cache, self) for cache in caches]
    self._fetcher = fetcher
    self._fetcher_provider = fetcher_provider
    self._install_cache = install_cache
    self._ws = WorkingSet([])
    with self.timed('Calling environment super'):
      super(Resolver, self).__init__(search_path=[], platform=platform, python=python)

  @property
  def fetcher(self):
    if not self._fetcher:
      self._fetcher = self._fetcher_provider()
    return self._fetcher

  def resolve(self, requirements, ignore_errors=False):
    if isinstance(requirements, (list, tuple, GeneratorType)):
      reqs = list(RequirementWrapper.get(req) for req in requirements)
    else:
      reqs = [RequirementWrapper.get(requirements)]
    resolved = OrderedSet()
    for req in reqs:
      with self.timed('Resolved %s' % req):
        try:
          distributions = self._ws.resolve([req], env=self)
        except DistributionNotFound as e:
          self._log('Failed to resolve %s' % req)
          if not ignore_errors:
            raise
          continue
        resolved.update(distributions)
    return list(resolved)

  def can_add(self, dist):
    def version_compatible():
      return any([self.python is None, dist.py_version is None, dist.py_version == self.python])
    def platform_compatible():
      return Platform.compatible(dist.platform, self.platform)
    return version_compatible() and platform_compatible()

  def best_match(self, req, *ignore_args, **ignore_kwargs):
    while True:
      resolved_req = super(Resolver, self).best_match(req, self._ws)
      if resolved_req:
        return resolved_req
      if all(subcache.activated for subcache in self._subcaches):
        print('Failed to resolve %s, your installation may not work properly.' % req, file=sys.stderr)
        break
      else:
        for subcache in self._subcaches:
          if not subcache.activated:
            subcache.activate()
            break

  def obtain(self, req, *ignore_args, **ignore_kwargs):
    if not all(subcache.activated for subcache in self._subcaches):
      # Only fetch once all subcaches have been exhausted.
      return None
    with self.timed('Fetching %s' % req):
      fetched_req = self.fetcher.fetch(req)
    if not fetched_req:
      print('Failed to fetch %s' % req)
      return None
    installer = Installer(fetched_req)
    with self.timed('Building %s' % req):
      try:
        dist = installer.distribution()
      except Installer.InstallFailure as e:
        print('Failed to install %s' % req, file=sys.stderr)
        return None
    if self._install_cache:
      with self.timed('Distilling %s' % req):
        distilled = Distiller(dist).distill(into=self._install_cache)
      with self.timed('Constructing distribution %s' % req):
        metadata = EggMetadata(EggZipImporter(distilled))
        dist = Distribution.from_filename(distilled, metadata)
    self.add(dist)
    return dist
