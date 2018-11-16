# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.crawler import Crawler
from pex.fetcher import Fetcher, PyPIFetcher
from pex.http import Context
from pex.installer import EggInstaller, WheelInstaller
from pex.iterator import Iterator
from pex.package import EggPackage, SourcePackage, WheelPackage
from pex.sorter import Sorter
from pex.third_party.pkg_resources import safe_name
from pex.translator import ChainedTranslator, EggTranslator, SourceTranslator, WheelTranslator


class ResolverOptionsInterface(object):
  def get_context(self):
    raise NotImplementedError

  def get_crawler(self):
    raise NotImplementedError

  def get_sorter(self):
    raise NotImplementedError

  def get_translator(self, interpreter, supported_tags):
    raise NotImplementedError

  def get_iterator(self):
    raise NotImplementedError


class ResolverOptionsBuilder(object):
  """A helper that processes options into a ResolverOptions object.

  Used by command-line and requirements.txt processors to configure a resolver.
  """

  def __init__(self,
               fetchers=None,
               allow_all_external=False,
               allow_external=None,
               allow_unverified=None,
               allow_prereleases=None,
               use_manylinux=None,
               precedence=None,
               context=None):
    self._fetchers = fetchers if fetchers is not None else [PyPIFetcher()]
    self._allow_all_external = allow_all_external
    self._allow_external = allow_external if allow_external is not None else set()
    self._allow_unverified = allow_unverified if allow_unverified is not None else set()
    self._allow_prereleases = allow_prereleases
    self._precedence = precedence if precedence is not None else Sorter.DEFAULT_PACKAGE_PRECEDENCE
    self._context = context or Context.get()
    self._use_manylinux = use_manylinux

  def clone(self):
    return ResolverOptionsBuilder(
        fetchers=self._fetchers[:],
        allow_all_external=self._allow_all_external,
        allow_external=self._allow_external.copy(),
        allow_unverified=self._allow_unverified.copy(),
        allow_prereleases=self._allow_prereleases,
        use_manylinux=self._use_manylinux,
        precedence=self._precedence[:],
        context=self._context,
    )

  def add_index(self, index):
    fetcher = PyPIFetcher(index)
    if fetcher not in self._fetchers:
      self._fetchers.append(fetcher)
    return self

  def set_index(self, index):
    self._fetchers = [PyPIFetcher(index)]
    return self

  def add_repository(self, repo):
    fetcher = Fetcher([repo])
    if fetcher not in self._fetchers:
      self._fetchers.append(fetcher)
    return self

  def clear_indices(self):
    self._fetchers = [fetcher for fetcher in self._fetchers if not isinstance(fetcher, PyPIFetcher)]
    return self

  def allow_all_external(self):
    self._allow_all_external = True
    return self

  def allow_external(self, key):
    self._allow_external.add(safe_name(key).lower())
    return self

  def allow_unverified(self, key):
    self._allow_unverified.add(safe_name(key).lower())
    return self

  def use_wheel(self):
    if WheelPackage not in self._precedence:
      self._precedence = (WheelPackage,) + self._precedence
    return self

  def no_use_wheel(self):
    self._precedence = tuple(
        [precedent for precedent in self._precedence if precedent is not WheelPackage])
    return self

  def use_manylinux(self):
    self._use_manylinux = True
    return self

  def no_use_manylinux(self):
    self._use_manylinux = False
    return self

  def allow_builds(self):
    if SourcePackage not in self._precedence:
      self._precedence = self._precedence + (SourcePackage,)
    return self

  def no_allow_builds(self):
    self._precedence = tuple(
        [precedent for precedent in self._precedence if precedent is not SourcePackage])
    return self

  # TODO: Make this whole interface more Pythonic.
  #
  # This method would be better defined as a property allow_prereleases.
  # Unfortunately, the existing method below already usurps the name allow_prereleases.
  # It is an existing API that returns self as if it was written in an attempt to allow
  # Java style chaining of method calls.
  # Due to that return type, it cannot be used as a Python property setter.
  # It's currently used in this manner:
  #
  #     builder.allow_prereleases(True)
  #
  # and we cannot change it into @allow_prereleases.setter and use in this manner:
  #
  #     builder.allow_prereleases = True
  #
  # without affecting the existing API calls.
  #
  # The code review shows that, for this particular method (allow_prereleases),
  # the return value (self) is never used in the current API calls.
  # It would be worth examining if the API change for this and some other methods here
  # would be a good idea.
  @property
  def prereleases_allowed(self):
    return self._allow_prereleases

  def allow_prereleases(self, allowed):
    self._allow_prereleases = allowed
    return self

  def build(self, key):
    return ResolverOptions(
        fetchers=self._fetchers,
        allow_external=self._allow_all_external or key in self._allow_external,
        allow_unverified=key in self._allow_unverified,
        allow_prereleases=self._allow_prereleases,
        use_manylinux=self._use_manylinux,
        precedence=self._precedence,
        context=self._context,
    )


class ResolverOptions(ResolverOptionsInterface):
  def __init__(self,
               fetchers=None,
               allow_external=False,
               allow_unverified=False,
               allow_prereleases=None,
               use_manylinux=None,
               precedence=None,
               context=None):
    self._fetchers = fetchers if fetchers is not None else [PyPIFetcher()]
    self._allow_external = allow_external
    self._allow_unverified = allow_unverified
    self._allow_prereleases = allow_prereleases
    self._use_manylinux = use_manylinux
    self._precedence = precedence if precedence is not None else Sorter.DEFAULT_PACKAGE_PRECEDENCE
    self._context = context or Context.get()

  # TODO(wickman) Revisit with Github #58
  def get_context(self):
    return self._context

  def get_crawler(self):
    return Crawler(self.get_context())

  # get_sorter and get_translator are arguably options that should be global
  # except that --no-use-wheel fucks this shit up.  hm.
  def get_sorter(self):
    return Sorter(self._precedence)

  def get_translator(self, interpreter, supported_tags):
    translators = []

    # TODO(wickman) This is not ideal -- consider an explicit link between a Package
    # and its Installer type rather than mapping this here, precluding the ability to
    # easily add new package types (or we just forego that forever.)
    for package in self._precedence:
      if package is WheelPackage:
        translators.append(WheelTranslator(supported_tags=supported_tags))
      elif package is EggPackage:
        translators.append(EggTranslator(supported_tags=supported_tags))
      elif package is SourcePackage:
        installer_impl = WheelInstaller if WheelPackage in self._precedence else EggInstaller
        translators.append(SourceTranslator(
            installer_impl=installer_impl,
            interpreter=interpreter,
            supported_tags=supported_tags))

    return ChainedTranslator(*translators)

  def get_iterator(self):
    return Iterator(
        fetchers=self._fetchers,
        crawler=self.get_crawler(),
        follow_links=self._allow_external,
        allow_prereleases=self._allow_prereleases
    )
