# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex import resolver
from pex.dist_metadata import Requirement
from pex.pep_427 import InstallableType
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.resolver_configuration import PipConfiguration, ResolverVersion
from pex.resolve.resolvers import Resolver, ResolveResult
from pex.targets import Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class ConfiguredResolver(Resolver):
    @classmethod
    def version(cls, pip_version):
        # type: (PipVersionValue) -> ConfiguredResolver
        return cls(
            PipConfiguration(
                version=pip_version, resolver_version=ResolverVersion.default(pip_version)
            )
        )

    @classmethod
    def default(cls):
        # type: () -> ConfiguredResolver
        return cls.version(PipVersion.DEFAULT)

    _pip_configuration = attr.ib()  # type: PipConfiguration

    @property
    def pip_configuration(self):
        # type: () -> PipConfiguration
        return self._pip_configuration

    def resolve_requirements(
        self,
        requirements,  # type: Iterable[str]
        targets=Targets(),  # type: Targets
        pip_version=None,  # type: Optional[PipVersionValue]
        transitive=None,  # type: Optional[bool]
        extra_resolver_requirements=None,  # type: Optional[Tuple[Requirement, ...]]
        result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
        constraint_files=None,  # type: Optional[Iterable[str]]
        compile=False,  # type: bool
        ignore_errors=False,  # type: bool
    ):
        # type: (...) -> ResolveResult
        return resolver.resolve(
            targets=targets,
            requirements=requirements,
            constraint_files=constraint_files,
            allow_prereleases=self._pip_configuration.allow_prereleases,
            transitive=transitive if transitive is not None else self._pip_configuration.transitive,
            repos_configuration=self._pip_configuration.repos_configuration,
            resolver_version=self._pip_configuration.resolver_version,
            network_configuration=self._pip_configuration.network_configuration,
            build_configuration=self._pip_configuration.build_configuration,
            compile=compile,
            max_parallel_jobs=self._pip_configuration.max_jobs,
            ignore_errors=ignore_errors,
            verify_wheels=True,
            pip_version=pip_version or self._pip_configuration.version,
            resolver=self,
            use_pip_config=self._pip_configuration.use_pip_config,
            extra_pip_requirements=(
                extra_resolver_requirements
                if extra_resolver_requirements is not None
                else self._pip_configuration.extra_requirements
            ),
            keyring_provider=self._pip_configuration.keyring_provider,
            result_type=result_type,
        )
