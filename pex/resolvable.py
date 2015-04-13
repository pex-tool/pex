# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod, abstractproperty

from pkg_resources import Requirement

from .base import maybe_requirement, requirement_is_exact
from .compatibility import string as compatibility_string
from .compatibility import AbstractClass
from .package import Package
from .resolver_options import ResolverOptionsBuilder, ResolverOptionsInterface


class Resolvable(AbstractClass):
  """An entity that can be resolved into a package."""

  class Error(Exception): pass
  class InvalidRequirement(Error): pass

  _REGISTRY = []

  @classmethod
  def register(cls, implementation):
    """Register an implementation of a Resolvable.

    :param implementation: The resolvable implementation.
    :type implementation: :class:`Resolvable`
    """
    cls._REGISTRY.append(implementation)

  @classmethod
  def get(cls, resolvable_string, options_builder=None):
    """Get a :class:`Resolvable` from a string.

    :returns: A :class:`Resolvable` or ``None`` if no implementation was appropriate.
    """
    options_builder = options_builder or ResolverOptionsBuilder()
    for resolvable_impl in cls._REGISTRY:
      try:
        return resolvable_impl.from_string(resolvable_string, options_builder)
      except cls.InvalidRequirement:
        continue
    raise cls.InvalidRequirement('Unknown requirement type: %s' % resolvable_string)

  # @abstractmethod - Only available in Python 3.3+
  @classmethod
  def from_string(cls, requirement_string, options_builder):
    """Produce a resolvable from this requirement string.

    :returns: Instance of the particular Resolvable implementation.
    :raises InvalidRequirement: If requirement_string is not a valid string representation
      of the resolvable.
    """
    raise cls.InvalidRequirement('Resolvable is abstract.')

  def __init__(self, options):
    if not isinstance(options, ResolverOptionsInterface):
      raise TypeError('Resolvable must be initialized with a ResolverOptionsInterface, got %s' % (
          type(options)))
    self._options = options

  @property
  def options(self):
    """The ResolverOptions for this Resolvable."""
    return self._options

  @abstractmethod
  def compatible(self, iterator):
    """Given a finder of type :class:`Iterator` (possibly ignored), determine which packages
       are compatible with this resolvable.

    :returns: An iterable of compatible :class:`Package` objects.
    """

  @abstractmethod
  def packages(self):
    """Return a list of :class:`Package` objects that this resolvable resolves.

    :returns: An iterable of compatible :class:`Package` objects.
    """

  @abstractproperty
  def name(self):
    """The distribution key associated with this resolvable, i.e. the name of the packages
       this resolvable will produce."""

  # TODO(wickman) Call this "cacheable" instead?
  @abstractproperty
  def exact(self):
    """Whether or not this resolvable specifies an exact (cacheable) requirement."""

  # TODO(wickman) Currently 'interpreter' is unused but it is reserved for environment
  # marker evaluation per PEP426 and:
  # https://bitbucket.org/pypa/setuptools/issue/353/allow-distributionrequires-be-evaluated
  def extras(self, interpreter=None):
    """Return the "extras" tags associated with this resolvable if any."""
    return []


class ResolvableRepository(Resolvable):
  """A VCS repository resolvable, e.g. 'git+', 'svn+', 'hg+', 'bzr+' packages."""

  COMPATIBLE_VCS = frozenset(['git', 'svn', 'hg', 'bzr'])

  @classmethod
  def from_string(cls, requirement_string, options_builder):
    if any(requirement_string.startswith('%s+' % vcs) for vcs in cls.COMPATIBLE_VCS):
      # further delegate
      pass

    # TODO(wickman) Implement.
    raise cls.InvalidRequirement('Versioning system URLs not supported.')

  def __init__(self, options):
    super(ResolvableRepository, self).__init__(options)

  def compatible(self, iterator):
    return []

  def packages(self):
    return []

  @property
  def name(self):
    raise NotImplemented

  @property
  def exact(self):
    return True


class ResolvablePackage(Resolvable):
  """A package (.tar.gz, .egg, .whl, etc) resolvable."""

  # TODO(wickman) Implement extras parsing for ResolvablePackage
  @classmethod
  def from_string(cls, requirement_string, options_builder):
    package = Package.from_href(requirement_string)
    if package is None:
      raise cls.InvalidRequirement('Requirement string does not appear to be a package.')
    return cls(package, options_builder.build(package.name))

  def __init__(self, package, options):
    self.package = package
    super(ResolvablePackage, self).__init__(options)

  def compatible(self, iterator):
    return []

  def packages(self):
    return [self.package]

  @property
  def name(self):
    return self.package.name

  @property
  def exact(self):
    return True

  # TODO(wickman) Implement extras parsing for ResolvablePackages
  def extras(self, interpreter=None):
    return []

  def __eq__(self, other):
    return isinstance(other, ResolvablePackage) and self.package == other.package

  def __hash__(self):
    return hash(self.package)

  def __str__(self):
    return str(self.package)


class ResolvableRequirement(Resolvable):
  """A requirement (e.g. 'setuptools', 'Flask>=0.8,<0.9', 'pex[whl]')."""

  @classmethod
  def from_string(cls, requirement_string, options_builder):
    try:
      req = maybe_requirement(requirement_string)
    except ValueError:
      raise cls.InvalidRequirement('%s does not appear to be a requirement string.' %
          requirement_string)
    return cls(req, options_builder.build(req.key))

  def __init__(self, requirement, options):
    self.requirement = requirement
    super(ResolvableRequirement, self).__init__(options)

  def compatible(self, iterator):
    sorter = self.options.get_sorter()
    return sorter.sort(package for package in iterator.iter(self.requirement))

  def packages(self):
    iterator = self.options.get_iterator()
    sorter = self.options.get_sorter()
    return sorter.sort(iterator.iter(self.requirement))

  @property
  def name(self):
    return self.requirement.key

  @property
  def exact(self):
    return requirement_is_exact(self.requirement)

  def extras(self, interpreter=None):
    return list(self.requirement.extras)

  def __eq__(self, other):
    return isinstance(other, ResolvableRequirement) and self.requirement == other.requirement

  def __hash__(self):
    return hash(self.requirement)

  def __str__(self):
    return str(self.requirement)


Resolvable.register(ResolvableRepository)
Resolvable.register(ResolvablePackage)
Resolvable.register(ResolvableRequirement)


# TODO(wickman) Because we explicitly acknowledge all implementations of Resolvable here,
# perhaps move away from a registry pattern and integrate into Resolvable classmethod.
def resolvables_from_iterable(iterable, builder):
  """Given an iterable of resolvable-like objects, return list of Resolvable objects.

  :param iterable: An iterable of :class:`Resolvable`, :class:`Requirement`, :class:`Package`,
      or `str` to map into an iterable of :class:`Resolvable` objects.
  :returns: A list of :class:`Resolvable` objects.
  """

  def translate(obj):
    if isinstance(obj, Resolvable):
      return obj
    elif isinstance(obj, Requirement):
      return ResolvableRequirement(obj, builder.build(obj.key))
    elif isinstance(obj, Package):
      return ResolvablePackage(obj, builder.build(obj.name))
    elif isinstance(obj, compatibility_string):
      return Resolvable.get(obj, builder)
    else:
      raise ValueError('Do not know how to resolve %s' % type(obj))
  return list(map(translate, iterable))
