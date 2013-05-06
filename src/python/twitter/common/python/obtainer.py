import itertools

from .http import EggLink, SourceLink
from .tracer import TRACER
from .translator import ChainedTranslator


class Obtainer(object):
  """
    A requirement obtainer.

    An Obtainer takes a Crawler, a list of Fetchers (which take requirements
    and tells us where to look for them) and a list of Translators (which
    translate egg or source links into usable distributions) and turns them
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
  def __init__(self, crawler, fetchers, translators):
    self._crawler = crawler
    self._fetchers = fetchers
    # use maybe_list?
    if isinstance(translators, (list, tuple)):
      self._translator = ChainedTranslator(*translators)
    else:
      self._translator = translators

  def translate_href(self, href):
    for link_class in (EggLink, SourceLink):
      try:
        return link_class(href, opener=self._crawler.opener)
      except link_class.InvalidLink:
        pass

  @classmethod
  def link_preference(cls, link):
    return (link.version, isinstance(link, EggLink))

  def iter_unordered(self, req):
    urls = list(itertools.chain(*[fetcher.urls(req) for fetcher in self._fetchers]))
    for link in filter(None, map(self.translate_href, self._crawler.crawl(*urls))):
      if link.satisfies(req):
        yield link

  def iter(self, req):
    """Given a req, return a list of links that satisfy the requirement in best match order."""
    for link in sorted(self.iter_unordered(req), key=self.link_preference, reverse=True):
      yield link

  def obtain(self, req):
    with TRACER.timed('Obtaining %s' % req):
      for link in self.iter(req):
        dist = self._translator.translate(link)
        if dist:
          return dist
