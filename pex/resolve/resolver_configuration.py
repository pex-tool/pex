# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools

from pex import pex_warnings
from pex.auth import PasswordEntry
from pex.enum import Enum
from pex.jobs import DEFAULT_MAX_JOBS
from pex.network_configuration import NetworkConfiguration
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion, PipVersionValue
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, FrozenSet, Iterable, Optional, Tuple, Union

    import attr  # vendor:skip

    from pex.resolve.lockfile.model import Lockfile
    from pex.result import Error
else:
    from pex.third_party import attr


PYPI = "https://pypi.org/simple"


class ResolverVersion(Enum["ResolverVersion.Value"]):
    class Value(Enum.Value):
        pass

    @staticmethod
    def _supports_legacy_resolver(pip_version=None):
        # type: (Optional[PipVersionValue]) -> bool
        pip_ver = pip_version or PipVersion.DEFAULT
        return pip_ver.version < Version("23.2")

    @classmethod
    def applies(
        cls,
        resolver_version,  # type: ResolverVersion.Value
        pip_version=None,
    ):
        # type: (...) -> bool
        return resolver_version is cls.PIP_2020 or cls._supports_legacy_resolver(pip_version)

    @classmethod
    def default(cls, pip_version=None):
        # type: (Optional[PipVersionValue]) -> ResolverVersion.Value
        return cls.PIP_LEGACY if cls._supports_legacy_resolver(pip_version) else cls.PIP_2020

    PIP_LEGACY = Value("pip-legacy-resolver")
    PIP_2020 = Value("pip-2020-resolver")


ResolverVersion.seal()


@attr.s(frozen=True)
class ReposConfiguration(object):
    @classmethod
    def create(
        cls,
        indexes=(),  # type: Iterable[str]
        find_links=(),  # type: Iterable[str]
    ):
        # type: (...) -> ReposConfiguration
        password_entries = []
        for url in itertools.chain(indexes, find_links):
            password_entry = PasswordEntry.maybe_extract_from_url(url)
            if password_entry:
                password_entries.append(password_entry)

        return cls(
            indexes=tuple(indexes),
            find_links=tuple(find_links),
            password_entries=tuple(password_entries),
        )

    indexes = attr.ib(default=(PYPI,))  # type: Tuple[str, ...]
    find_links = attr.ib(default=())  # type: Tuple[str, ...]
    password_entries = attr.ib(default=())  # type: Tuple[PasswordEntry, ...]


@attr.s(frozen=True)
class BuildConfiguration(object):
    class Error(ValueError):
        """Indicates a build configuration error."""

    @classmethod
    def create(
        cls,
        allow_builds=True,  # type: bool
        only_builds=(),  # type: Iterable[ProjectName]
        allow_wheels=True,  # type: bool
        only_wheels=(),  # type: Iterable[ProjectName]
        prefer_older_binary=False,  # type: bool
        use_pep517=None,  # type: Optional[bool]
        build_isolation=True,  # type: bool
        use_system_time=False,  # type: bool
    ):
        # type: (...) -> BuildConfiguration
        return cls(
            allow_builds=allow_builds,
            only_builds=frozenset(only_builds),
            allow_wheels=allow_wheels,
            only_wheels=frozenset(only_wheels),
            prefer_older_binary=prefer_older_binary,
            use_pep517=use_pep517,
            build_isolation=build_isolation,
            use_system_time=use_system_time,
        )

    allow_builds = attr.ib(default=True)  # type: bool
    only_builds = attr.ib(default=frozenset())  # type: FrozenSet[ProjectName]
    allow_wheels = attr.ib(default=True)  # type: bool
    only_wheels = attr.ib(default=frozenset())  # type: FrozenSet[ProjectName]
    prefer_older_binary = attr.ib(default=False)  # type: bool
    use_pep517 = attr.ib(default=None)  # type: Optional[bool]
    build_isolation = attr.ib(default=True)  # type: bool
    use_system_time = attr.ib(default=False)  # type: bool

    def __attrs_post_init__(self):
        # type: () -> None
        if not self.allow_builds and not self.allow_wheels:
            raise self.Error(
                "Cannot both disallow builds and disallow wheels. Please allow one of these or "
                "both so that some distributions can be resolved."
            )
        if not self.allow_builds and self.only_builds:
            raise self.Error(
                "Builds were disallowed, but the following project names are configured to only "
                "allow building: {only_builds}".format(
                    only_builds=", ".join(sorted(map(str, self.only_builds)))
                )
            )
        if not self.allow_wheels and self.only_wheels:
            raise self.Error(
                "Resolving wheels was disallowed, but the following project names are configured "
                "to only allow resolving pre-built wheels: {only_wheels}".format(
                    only_wheels=", ".join(sorted(map(str, self.only_wheels)))
                )
            )

        contradictory_only = self.only_builds.intersection(self.only_wheels)
        if contradictory_only:
            raise self.Error(
                "The following project names were specified as only being allowed to be built and "
                "only allowed to be resolved as pre-built wheels, please pick one or the other for "
                "each: {contradictory_only}".format(
                    contradictory_only=", ".join(sorted(map(str, contradictory_only)))
                )
            )

        if self.prefer_older_binary and not (self.allow_wheels and self.allow_builds):
            pex_warnings.warn(
                "The prefer older binary setting was requested, but this has no effect unless both "
                "pre-built wheels and sdist builds are allowed."
            )

        if not self.allow_builds and self.use_pep517 is not None:
            pex_warnings.warn(
                "Use of PEP-517 builds was set to {value}, but builds are turned off; so this "
                "setting has no effect.".format(value=self.use_pep517)
            )

        if not self.allow_builds and not self.build_isolation:
            pex_warnings.warn(
                "Build isolation was turned off, but builds are also turned off; so this setting "
                "has no effect."
            )

    def allow_build(self, project_name):
        # type: (ProjectName) -> bool
        return self.allow_builds and project_name not in self.only_wheels

    def allow_wheel(self, project_name):
        # type: (ProjectName) -> bool
        return self.allow_wheels and project_name not in self.only_builds


@attr.s(frozen=True)
class PipLog(object):
    path = attr.ib()  # type: str
    user_specified = attr.ib()  # type: bool


@attr.s(frozen=True)
class PipConfiguration(object):
    repos_configuration = attr.ib(default=ReposConfiguration())  # type: ReposConfiguration
    network_configuration = attr.ib(default=NetworkConfiguration())  # type: NetworkConfiguration
    build_configuration = attr.ib(default=BuildConfiguration())  # type: BuildConfiguration
    allow_prereleases = attr.ib(default=False)  # type: bool
    transitive = attr.ib(default=True)  # type: bool
    max_jobs = attr.ib(default=DEFAULT_MAX_JOBS)  # type: int
    log = attr.ib(default=None)  # type: Optional[PipLog]
    version = attr.ib(default=None)  # type: Optional[PipVersionValue]
    resolver_version = attr.ib(default=None)  # type: Optional[ResolverVersion.Value]
    allow_version_fallback = attr.ib(default=True)  # type: bool
    use_pip_config = attr.ib(default=False)  # type: bool
    extra_requirements = attr.ib(default=())  # type Tuple[Requirement, ...]
    keyring_provider = attr.ib(default=None)  # type: Optional[str]


@attr.s(frozen=True)
class PexRepositoryConfiguration(object):
    pex_repository = attr.ib()  # type: str
    pip_configuration = attr.ib()  # type: PipConfiguration

    @property
    def repos_configuration(self):
        # type: () -> ReposConfiguration
        return self.pip_configuration.repos_configuration

    @property
    def network_configuration(self):
        # type: () -> NetworkConfiguration
        return self.pip_configuration.network_configuration

    @property
    def transitive(self):
        # type: () -> bool
        return self.pip_configuration.transitive


@attr.s(frozen=True)
class LockRepositoryConfiguration(object):
    parse_lock = attr.ib()  # type: Callable[[], Union[Lockfile, Error]]
    lock_file_path = attr.ib()  # type: str
    pip_configuration = attr.ib()  # type: PipConfiguration

    @property
    def repos_configuration(self):
        # type: () -> ReposConfiguration
        return self.pip_configuration.repos_configuration

    @property
    def network_configuration(self):
        # type: () -> NetworkConfiguration
        return self.pip_configuration.network_configuration


@attr.s(frozen=True)
class PreResolvedConfiguration(object):
    sdists = attr.ib()  # type: Tuple[str, ...]
    wheels = attr.ib()  # type: Tuple[str, ...]
    pip_configuration = attr.ib()  # type: PipConfiguration

    @property
    def repos_configuration(self):
        # type: () -> ReposConfiguration
        return self.pip_configuration.repos_configuration

    @property
    def network_configuration(self):
        # type: () -> NetworkConfiguration
        return self.pip_configuration.network_configuration
