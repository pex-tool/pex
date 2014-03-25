import itertools

from .fetcher import PyPIFetcher
from .http import Crawler
from .package import (
     EggPackage,
     Package,
     SourcePackage,
)
from .tracer import TRACER
from .translator import ChainedTranslator, Translator


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
  def default(cls):
    return cls(Crawler(), fetchers=[PyPIFetcher()], translators=Translator.default())

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
    if isinstance(translators, (list, tuple)):
      self._translator = ChainedTranslator(*translators)
    else:
      self._translator = translators
    self._precedence = precedence

  @property
  def translator(self):
    return self._translator

  def translate_href(self, href):
    return Package.from_href(href, opener=self._crawler.opener)

  def iter_unordered(self, req):
    urls = list(itertools.chain(*[fetcher.urls(req) for fetcher in self._fetchers]))
    for package in filter(None, map(self.translate_href, self._crawler.crawl(*urls))):
      if package.satisfies(req):
        yield package

  def sort(self, package_list):
    key = lambda package: self.package_precedence(package, self._precedence)
    return sorted(package_list, key=key, reverse=True)

  def iter(self, req):
    """Given a req, return a list of packages that satisfy the requirement in best match order."""
    for package in self.sort(self.iter_unordered(req)):
      yield package

  def translate_from(self, obtain_set):
    for package in obtain_set:
      dist = self._translator.translate(package)
      if dist:
        return dist

  def obtain(self, req):
    with TRACER.timed('Obtaining %s' % req):
      return self.translate_from(list(self.iter(req)))


class ObtainerFactory(object):
  """Returns an `Obtainer` for the given `Requirement`."""
  def __call__(self, requirement):
    raise NotImplementedError()


class DefaultObtainerFactory(ObtainerFactory):
  """Always return `Obtainer.default()` for the given requirement. """
  _OBTAINER = Obtainer.default()

  def __call__(self, _):
    return self._OBTAINER
