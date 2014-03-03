from __future__ import print_function

from .base import maybe_requirement_list
from .fetcher import Fetcher, PyPIFetcher
from .http import Crawler
from .interpreter import PythonInterpreter
from .obtainer import Obtainer
from .platforms import Platform
from .translator import (
    ChainedTranslator,
    EggTranslator,
    SourceTranslator,
)

from pkg_resources import (
    Environment,
    WorkingSet,
)


class ResolverEnvironment(Environment):
  def can_add(self, dist):
    return Platform.distribution_compatible(dist, python=self.python, platform=self.platform)


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
  shared_options = dict(install_cache=cache, platform=platform)
  egg_translator = EggTranslator(python=interpreter.python, **shared_options)
  cache_obtainer = Obtainer(crawler, [Fetcher([cache])], egg_translator) if cache else None
  source_translator = SourceTranslator(interpreter=interpreter, **shared_options)
  translator = ChainedTranslator(egg_translator, source_translator)
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
  env = ResolverEnvironment(search_path=[], platform=platform, python=interpreter.python)
  return working_set.resolve(requirements, env=env, installer=installer)
