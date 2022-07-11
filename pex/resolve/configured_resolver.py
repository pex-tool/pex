# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex import resolver
from pex.resolve import lock_resolver
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.resolver_configuration import PipConfiguration, ReposConfiguration
from pex.resolve.resolvers import Installed, Resolver
from pex.result import try_
from pex.targets import Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable

    import attr  # vendor:skip
else:
    from pex.third_party import attr


_DEFAULT_REPOS = ReposConfiguration.create()


@attr.s(frozen=True)
class ConfiguredResolver(Resolver):
    @classmethod
    def default(cls):
        # type: () -> ConfiguredResolver
        return cls(PipConfiguration())

    pip_configuration = attr.ib()  # type: PipConfiguration

    def is_default_repos(self):
        return self.pip_configuration.repos_configuration == _DEFAULT_REPOS

    def resolve_lock(
        self,
        lock,  # type: Lockfile
        targets=Targets(),  # type: Targets
    ):
        # type: (...) -> Installed
        return try_(
            lock_resolver.resolve_from_lock(
                targets=targets,
                lock=lock,
                resolver=self,
                indexes=self.pip_configuration.repos_configuration.indexes,
                find_links=self.pip_configuration.repos_configuration.find_links,
                resolver_version=self.pip_configuration.resolver_version,
                network_configuration=self.pip_configuration.network_configuration,
                build=self.pip_configuration.allow_builds,
                use_wheel=self.pip_configuration.allow_wheels,
                prefer_older_binary=self.pip_configuration.prefer_older_binary,
                use_pep517=self.pip_configuration.use_pep517,
                build_isolation=self.pip_configuration.build_isolation,
                compile=False,
                transitive=self.pip_configuration.transitive,
                verify_wheels=True,
                max_parallel_jobs=self.pip_configuration.max_jobs,
            )
        )

    def resolve_requirements(
        self,
        requirements,  # type: Iterable[str]
        targets=Targets(),  # type: Targets
    ):
        # type: (...) -> Installed
        return resolver.resolve(
            targets=targets,
            requirements=requirements,
            allow_prereleases=False,
            transitive=self.pip_configuration.transitive,
            indexes=self.pip_configuration.repos_configuration.indexes,
            find_links=self.pip_configuration.repos_configuration.find_links,
            resolver_version=self.pip_configuration.resolver_version,
            network_configuration=self.pip_configuration.network_configuration,
            build=self.pip_configuration.allow_builds,
            use_wheel=self.pip_configuration.allow_wheels,
            prefer_older_binary=self.pip_configuration.prefer_older_binary,
            use_pep517=self.pip_configuration.use_pep517,
            build_isolation=self.pip_configuration.build_isolation,
            compile=False,
            max_parallel_jobs=self.pip_configuration.max_jobs,
            ignore_errors=False,
            verify_wheels=True,
        )
