# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.network_configuration import NetworkConfiguration
from pex.pip.configuration import PipConfiguration
from pex.resolve.package_repository import ReposConfiguration
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Callable, FrozenSet, Tuple, Union

    import attr  # vendor:skip

    from pex.resolve.lockfile.model import Lockfile
    from pex.result import Error
else:
    from pex.third_party import attr


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
class PylockRepositoryConfiguration(object):
    lock_file_path = attr.ib()  # type: str
    extras = attr.ib()  # type: FrozenSet[str]
    dependency_groups = attr.ib()  # type: FrozenSet[str]
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


@attr.s(frozen=True)
class VenvRepositoryConfiguration(object):
    venvs = attr.ib()  # type: Tuple[Virtualenv, ...]
    pip_configuration = attr.ib()  # type: PipConfiguration

    @property
    def repos_configuration(self):
        # type: () -> ReposConfiguration
        return self.pip_configuration.repos_configuration

    @property
    def network_configuration(self):
        # type: () -> NetworkConfiguration
        return self.pip_configuration.network_configuration
