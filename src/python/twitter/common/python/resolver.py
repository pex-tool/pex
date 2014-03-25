from __future__ import print_function

from collections import defaultdict

from .interpreter import PythonInterpreter
from .obtainer import DefaultObtainerFactory
from .orderedset import OrderedSet
from .package import Package, distribution_compatible
from .platforms import Platform

from pkg_resources import Distribution


class Untranslateable(Exception):
  pass


class Unsatisfiable(Exception):
  pass


class _DistributionCache(object):
  _ERROR_MSG = 'Expected %s but got %s'

  def __init__(self):
    self._translated_packages = {}

  def has(self, package):
    if not isinstance(package, Package):
      raise ValueError(self._ERROR_MSG % (Package, package))
    return package in self._translated_packages

  def put(self, package, distribution):
    if not isinstance(package, Package):
      raise ValueError(self._ERROR_MSG % (Package, package))
    if not isinstance(distribution, Distribution):
      raise ValueError(self._ERROR_MSG % (Distribution, distribution))
    self._translated_packages[package] = distribution

  def get(self, package):
    if not isinstance(package, Package):
      raise ValueError(self._ERROR_MSG % (Package, package))
    return self._translated_packages[package]


def resolve(requirements, obtainer_factory=None, interpreter=None, platform=None):
  """List all distributions needed to (recursively) meet `requirements`

  When resolving dependencies, multiple (potentially incompatible) requirements may be encountered.
  Handle this situation by iteratively filtering a set of potential project
  distributions by new requirements, and finally choosing the highest version meeting all
  requirements, or raise an error indicating unsatisfiable requirements.

  Note: should `pkg_resources.WorkingSet.resolve` correctly handle multiple requirements in the
  future this should go away in favor of using what setuptools provides.

  :returns: List of :class:`pkg_resources.Distribution` instances meeting `requirements`.
  """
  cache = _DistributionCache()
  obtainer_factory = obtainer_factory or DefaultObtainerFactory
  interpreter = interpreter or PythonInterpreter.get()
  platform = platform or Platform.current()

  requirements = list(requirements)
  distribution_set = defaultdict(list)
  requirement_set = defaultdict(list)
  processed_requirements = set()

  def packages(requirement, obtainer, interpreter, platform, existing=None):
    if existing is None:
      existing = obtainer.iter(requirement)
    return [package for package in existing
            if package.satisfies(requirement)
            and package.compatible(interpreter.identity, platform)]

  def requires(package, translator, requirement):
    if not cache.has(package):
      dist = translator.translate(package)
      if dist is None:
        raise Untranslateable('Package %s is not translateable.' % package)
      if not distribution_compatible(dist, interpreter, platform):
        raise Untranslateable('Could not get distribution for %s on appropriate platform.' % package)
      cache.put(package, dist)
    dist = cache.get(package)
    return dist.requires(extras=requirement.extras)

  while True:
    while requirements:
      requirement = requirements.pop(0)
      requirement_set[requirement.key].append(requirement)
      obtainer = obtainer_factory(requirement)
      distribution_list = distribution_set[requirement.key] = packages(
          requirement,
          obtainer,
          interpreter,
          platform,
          existing=distribution_set.get(requirement.key))
      if not distribution_list:
        raise Unsatisfiable('Cannot satisfy requirements: %s' % requirement_set[requirement.key])

    # get their dependencies
    for requirement_key, requirement_list in requirement_set.items():
      new_requirements = OrderedSet()
      highest_package = distribution_set[requirement_key][0]
      for requirement in requirement_list:
        if requirement in processed_requirements:
          continue
        new_requirements.update(
          requires(highest_package, obtainer_factory(requirement).translator, requirement))
        processed_requirements.add(requirement)
      requirements.extend(list(new_requirements))

    if not requirements:
      break

  to_activate = set()
  for distributions in distribution_set.values():
    to_activate.add(cache.get(distributions[0]))
  return to_activate

def requirement_is_exact(req):
  return req.specs and len(req.specs) == 1 and req.specs[0][0] == '=='
