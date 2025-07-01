# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Namespace, _ActionsContainer

from pex import dependency_configuration
from pex import resolver as pip_resolver
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import is_wheel
from pex.exceptions import reportable_unexpected_error_msg
from pex.orderedset import OrderedSet
from pex.pip.tool import PackageIndexConfiguration
from pex.resolve import lock_resolver, requirement_options, resolver_options, target_options
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.lockfile.download_manager import DownloadedArtifact
from pex.resolve.lockfile.pep_751 import Pylock
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import (
    LockRepositoryConfiguration,
    PipConfiguration,
    PylockRepositoryConfiguration,
)
from pex.resolve.resolvers import Resolver
from pex.resolve.target_configuration import TargetConfiguration
from pex.resolver import BuildRequest, LocalDistribution, WheelBuilder
from pex.result import Error, try_
from pex.targets import Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple, Union

    import attr  # vendor:skip

    from pex.resolve.resolver_options import ResolverConfiguration
else:
    from pex.third_party import attr


def register_options(parser):
    # type: (_ActionsContainer) -> None

    requirement_options.register(parser)
    resolver_options.register(parser, include_pex_lock=True, include_pylock=True)
    target_options.register(parser, include_platforms=True)
    dependency_configuration.register(parser)


@attr.s(frozen=True)
class Configuration(object):
    requirement_configuration = attr.ib()  # type: RequirementConfiguration
    dependency_configuration = attr.ib()  # type: DependencyConfiguration
    resolver_configuration = attr.ib()  # type: ResolverConfiguration
    pip_configuration = attr.ib()  # type: PipConfiguration
    target_configuration = attr.ib()  # type: TargetConfiguration

    def resolver(self):
        # type: () -> Resolver
        return ConfiguredResolver(pip_configuration=self.pip_configuration)

    def resolve_targets(self):
        # type: () -> Targets
        return self.target_configuration.resolve_targets()


def configure(options):
    # type: (Namespace) -> Configuration

    resolver_configuration = resolver_options.configure(options)
    pip_configuration = (
        resolver_configuration
        if isinstance(resolver_configuration, PipConfiguration)
        else resolver_configuration.pip_configuration
    )
    return Configuration(
        requirement_configuration=requirement_options.configure(options),
        dependency_configuration=dependency_configuration.configure(options),
        resolver_configuration=resolver_configuration,
        pip_configuration=pip_configuration,
        target_configuration=target_options.configure(options, pip_configuration=pip_configuration),
    )


@attr.s(frozen=True)
class WheelDist(object):
    path = attr.ib()  # type: str


@attr.s(frozen=True)
class SourceDist(object):
    path = attr.ib()  # type: str
    subdirectory = attr.ib(default=None)  # type: Optional[str]


if TYPE_CHECKING:
    Dist = Union[SourceDist, WheelDist]
    DownloadedItem = Union[DownloadedArtifact, LocalDistribution]


def _to_dists(downloaded_artifacts):
    # type: (Iterable[DownloadedItem]) -> Tuple[Dist, ...]

    def to_dist(downloaded_artifact):
        # type: (DownloadedItem) -> Dist
        if is_wheel(downloaded_artifact.path):
            return WheelDist(downloaded_artifact.path)
        return SourceDist(downloaded_artifact.path, subdirectory=downloaded_artifact.subdirectory)

    return tuple(map(to_dist, downloaded_artifacts))


def download_distributions(configuration):
    # type: (Configuration) -> Union[Tuple[Union[SourceDist, WheelDist], ...], Error]

    requirement_configuration = configuration.requirement_configuration
    dep_configuration = configuration.dependency_configuration
    resolver_configuration = configuration.resolver_configuration
    pip_configuration = configuration.pip_configuration

    resolver = configuration.resolver()
    targets = configuration.resolve_targets()

    if isinstance(resolver_configuration, LockRepositoryConfiguration):
        lock = try_(resolver_configuration.parse_lock())
        return _to_dists(
            try_(
                lock_resolver.download_from_pex_lock(
                    targets,
                    lock,
                    resolver,
                    requirements=requirement_configuration.requirements,
                    requirement_files=requirement_configuration.requirement_files,
                    constraint_files=requirement_configuration.constraint_files,
                    indexes=resolver_configuration.repos_configuration.indexes,
                    find_links=resolver_configuration.repos_configuration.find_links,
                    resolver_version=pip_configuration.resolver_version,
                    network_configuration=resolver_configuration.network_configuration,
                    password_entries=pip_configuration.repos_configuration.password_entries,
                    build_configuration=pip_configuration.build_configuration,
                    transitive=pip_configuration.transitive,
                    max_parallel_jobs=pip_configuration.max_jobs,
                    pip_version=pip_configuration.version,
                    use_pip_config=pip_configuration.use_pip_config,
                    extra_pip_requirements=pip_configuration.extra_requirements,
                    keyring_provider=pip_configuration.keyring_provider,
                    dependency_configuration=dep_configuration,
                )
            )
        )
    elif isinstance(resolver_configuration, PylockRepositoryConfiguration):
        pylock = try_(Pylock.parse(resolver_configuration.lock_file_path))
        return _to_dists(
            try_(
                lock_resolver.download_from_pylock(
                    targets,
                    pylock,
                    resolver,
                    requirements=requirement_configuration.requirements,
                    requirement_files=requirement_configuration.requirement_files,
                    extras=resolver_configuration.extras,
                    dependency_groups=resolver_configuration.dependency_groups,
                    constraint_files=requirement_configuration.constraint_files,
                    indexes=resolver_configuration.repos_configuration.indexes,
                    find_links=resolver_configuration.repos_configuration.find_links,
                    resolver_version=pip_configuration.resolver_version,
                    network_configuration=resolver_configuration.network_configuration,
                    password_entries=pip_configuration.repos_configuration.password_entries,
                    build_configuration=pip_configuration.build_configuration,
                    transitive=pip_configuration.transitive,
                    max_parallel_jobs=pip_configuration.max_jobs,
                    pip_version=pip_configuration.version,
                    use_pip_config=pip_configuration.use_pip_config,
                    extra_pip_requirements=pip_configuration.extra_requirements,
                    keyring_provider=pip_configuration.keyring_provider,
                    dependency_configuration=dep_configuration,
                )
            )
        )
    elif isinstance(resolver_configuration, PipConfiguration):
        return _to_dists(
            try_(
                pip_resolver.download(
                    targets=targets,
                    requirements=requirement_configuration.requirements,
                    requirement_files=requirement_configuration.requirement_files,
                    constraint_files=requirement_configuration.constraint_files,
                    allow_prereleases=pip_configuration.allow_prereleases,
                    transitive=pip_configuration.transitive,
                    indexes=resolver_configuration.repos_configuration.indexes,
                    find_links=resolver_configuration.repos_configuration.find_links,
                    resolver_version=pip_configuration.resolver_version,
                    network_configuration=resolver_configuration.network_configuration,
                    password_entries=pip_configuration.repos_configuration.password_entries,
                    build_configuration=pip_configuration.build_configuration,
                    max_parallel_jobs=pip_configuration.max_jobs,
                    pip_log=pip_configuration.log,
                    pip_version=pip_configuration.version,
                    resolver=resolver,
                    use_pip_config=pip_configuration.use_pip_config,
                    extra_pip_requirements=pip_configuration.extra_requirements,
                    keyring_provider=pip_configuration.keyring_provider,
                    dependency_configuration=dep_configuration,
                )
            ).local_distributions
        )
    else:
        return Error(
            reportable_unexpected_error_msg(
                "Pex should only allow the download subcommand against Pex lock files, PEP-751 "
                "lock files (pylock.toml) and simple index / find-links configurations. "
                "Encountered an unexpected `{resolver_configuration}` resolver "
                "configuration.".format(
                    resolver_configuration=type(resolver_configuration).__name__
                )
            )
        )


def build_wheels(
    configuration,  # type: Configuration
    build_requests,  # type: Iterable[BuildRequest]
    check_compatible=True,  # type: bool
):
    # type: (...) -> Union[Tuple[str, ...], Error]

    wheel_builder = WheelBuilder(
        package_index_configuration=PackageIndexConfiguration.create(
            pip_version=configuration.pip_configuration.version,
            resolver_version=configuration.pip_configuration.resolver_version,
            indexes=configuration.pip_configuration.repos_configuration.indexes,
            find_links=configuration.pip_configuration.repos_configuration.find_links,
            network_configuration=configuration.pip_configuration.network_configuration,
            password_entries=configuration.pip_configuration.repos_configuration.password_entries,
            use_pip_config=configuration.pip_configuration.use_pip_config,
            extra_pip_requirements=configuration.pip_configuration.extra_requirements,
            keyring_provider=configuration.pip_configuration.keyring_provider,
        ),
        build_configuration=configuration.pip_configuration.build_configuration,
        pip_version=configuration.pip_configuration.version,
        resolver=configuration.resolver(),
    )

    results = wheel_builder.build_wheels(
        build_requests, configuration.pip_configuration.max_jobs, check_compatible=check_compatible
    )
    return tuple(
        OrderedSet(
            install_request.wheel_path
            for install_requests in results.values()
            for install_request in install_requests
        )
    )
