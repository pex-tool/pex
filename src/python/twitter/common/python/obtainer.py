import itertools

from .package import (
     EggPackage,
     Package,
     SourcePackage,
)
from .tracer import TRACER
from .translator import ChainedTranslator


class Obtainer(object):
  """
    A requirement obtainer.

    An Obtainer takes a Crawler, a list of Fetchers (which take requirements
    and tells us where to look for them) and a list of Translators (which
    translate egg or source packages into usable distributions) and turns them
    into a cohesive requirement pipeline.

    >>> from twitter.common.python.http import Crawler
    >>> from twitter.common.python.obtainer import Obtainer
    >>> from twitter.common.python.fetcher import PyPIFetcher
    >>> from twitter.common.python.resolver import Resolver
    >>> from twitter.common.python.translator import Translator
    >>> obtainer = Obtainer(Crawler(), [PyPIFetcher()], [Translator.default()])
    >>> resolver = Resolver(obtainer)
    >>> distributions = resolver.resolve(['ansicolors', 'elementtree', 'mako', 'markdown', 'psutil',
    ...                                   'pygments', 'pylint', 'pytest'])
    >>> for d in distributions: d.activate()
  """
  DEFAULT_PACKAGE_PRECEDENCE = (
      EggPackage,
      SourcePackage,
  )

  @classmethod
  def package_type_precedence(cls, package, precedence=DEFAULT_PACKAGE_PRECEDENCE):
    for rank, package_type in enumerate(reversed(precedence)):
      if isinstance(package, package_type):
        return rank
    # If we do not recognize the package, it gets lowest precedence
    return -1

  @classmethod
  def package_precedence(cls, package, precedence=DEFAULT_PACKAGE_PRECEDENCE):
    return (package.version, cls.package_type_precedence(package, precedence=precedence))

  def __init__(self, crawler, fetchers, translators, precedence=DEFAULT_PACKAGE_PRECEDENCE):
    self._crawler = crawler
    self._fetchers = fetchers
    # use maybe_list?
    if isinstance(translators, (list, tuple)):
      self._translator = ChainedTranslator(*translators)
    else:
      self._translator = translators
    self._precedence = precedence

  def translate_href(self, href):
    return Package.from_href(href, opener=self._crawler.opener)

  def iter_unordered(self, req):
    urls = list(itertools.chain(*[fetcher.urls(req) for fetcher in self._fetchers]))
    for package in filter(None, map(self.translate_href, self._crawler.crawl(*urls))):
      if package.satisfies(req):
        yield package

  def iter(self, req):
    """Given a req, return a list of packages that satisfy the requirement in best match order."""
    key = lambda package: self.package_precedence(package, self._precedence)
    for package in sorted(self.iter_unordered(req), key=key, reverse=True):
      yield package

  def obtain(self, req):
    with TRACER.timed('Obtaining %s' % req):
      packages = list(self.iter(req))
      for package in packages:
        dist = self._translator.translate(package)
        if dist:
          return dist
