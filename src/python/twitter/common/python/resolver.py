from __future__ import print_function

from .base import maybe_requirement_list
from .fetcher import Fetcher, PyPIFetcher
from .http import Crawler
from .interpreter import PythonInterpreter
from .obtainer import Obtainer
from .package import distribution_compatible
from .platforms import Platform
from .translator import (
    ChainedTranslator,
    EggTranslator,
    Translator,
)

from pkg_resources import (
    Environment,
    WorkingSet,
)


class ResolverEnvironment(Environment):
  def __init__(self, interpreter, *args, **kw):
    kw['python'] = interpreter.python
    self.__interpreter = interpreter
    super(ResolverEnvironment, self).__init__(*args, **kw)

  def can_add(self, dist):
    return distribution_compatible(dist, self.__interpreter, platform=self.platform)


def requirement_is_exact(req):
  return req.specs and len(req.specs) == 1 and req.specs[0][0] == '=='


def resolve(requirements,
            cache=None,
            crawler=None,
            fetchers=None,
            obtainer=None,
            interpreter=None,
            platform=None):
  """Resolve a list of requirements into distributions.

     :param requirements: A list of strings or :class:`pkg_resources.Requirement` objects to be
                          resolved.
     :param cache: The filesystem path to cache distributions or None for no caching.
     :param crawler: The :class:`Crawler` object to use to crawl for artifacts.  If None specified
                     a default crawler will be constructed.
     :param fetchers: A list of :class:`Fetcher` objects for generating links.  If None specified,
                      default to fetching from PyPI.
     :param obtainer: An :class:`Obtainer` object for converting from links to
                      :class:`pkg_resources.Distribution` objects.  If None specified, a default
                      will be provided that accepts eggs or building from source.
     :param interpreter: A :class:`PythonInterpreter` object to resolve against.  If None specified,
                         use the current interpreter.
     :param platform: The string representing the platform to be resolved, such as `'linux-x86_64'`
                      or `'macosx-10.7-intel'`.  If None specified, the current platform is used.
  """
  requirements = maybe_requirement_list(requirements)

  # Construct defaults
  crawler = crawler or Crawler()
  fetchers = fetchers or [PyPIFetcher()]
  interpreter = interpreter or PythonInterpreter.get()
  platform = platform or Platform.current()

  # wire up translators / obtainer
  if cache:
    shared_options = dict(install_cache=cache, platform=platform, interpreter=interpreter)
    translator = EggTranslator(**shared_options)
    cache_obtainer = Obtainer(crawler, [Fetcher([cache])], translator)
  else:
    cache_obtainer = None

  if not obtainer:
    translator = Translator.default(install_cache=cache, platform=platform, interpreter=interpreter)
    obtainer = Obtainer(crawler, fetchers, translator)

  # make installer
  def installer(req):
    if cache_obtainer and requirement_is_exact(req):
      dist = cache_obtainer.obtain(req)
      if dist:
        return dist
    return obtainer.obtain(req)

  # resolve
  working_set = WorkingSet(entries=[])
  env = ResolverEnvironment(interpreter, search_path=[], platform=platform)
  return working_set.resolve(requirements, env=env, installer=installer)
