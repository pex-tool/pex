# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

from pex import dependency_configuration
from pex import resolver as pip_resolver
from pex.cli.command import BuildTimeCommand
from pex.common import safe_copy, safe_mkdir
from pex.exceptions import reportable_unexpected_error_msg
from pex.resolve import lock_resolver, requirement_options, resolver_options, target_options
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.lockfile.pep_751 import Pylock
from pex.resolve.resolver_configuration import (
    LockRepositoryConfiguration,
    PipConfiguration,
    PylockRepositoryConfiguration,
)
from pex.result import Error, Ok, Result, try_


class Download(BuildTimeCommand):
    """Download distributions instead of resolving them into a PEX."""

    @classmethod
    def add_extra_arguments(cls, parser):
        parser.add_argument(
            "-d",
            "--dest-dir",
            metavar="PATH",
            required=True,
            help="The path to download distribution to.",
        )
        requirement_options.register(parser)
        resolver_options.register(parser, include_pex_lock=True, include_pylock=True)
        target_options.register(parser, include_platforms=True)
        dependency_configuration.register(parser)

    def run(self):
        # type: () -> Result

        requirement_configuration = requirement_options.configure(self.options)
        dep_configuration = dependency_configuration.configure(self.options)
        resolver_configuration = resolver_options.configure(self.options)
        pip_configuration = (
            resolver_configuration
            if isinstance(resolver_configuration, PipConfiguration)
            else resolver_configuration.pip_configuration
        )
        resolver = ConfiguredResolver(pip_configuration=pip_configuration)
        targets = target_options.configure(
            self.options, pip_configuration=pip_configuration
        ).resolve_targets()

        if isinstance(resolver_configuration, LockRepositoryConfiguration):
            lock = try_(resolver_configuration.parse_lock())
            artifact_paths = try_(
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
        elif isinstance(resolver_configuration, PylockRepositoryConfiguration):
            pylock = try_(Pylock.parse(resolver_configuration.lock_file_path))
            artifact_paths = try_(
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
        elif isinstance(resolver_configuration, PipConfiguration):
            artifact_paths = tuple(
                local_distribution.path
                for local_distribution in try_(
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

        safe_mkdir(self.options.dest_dir)
        for path in artifact_paths:
            safe_copy(path, os.path.join(self.options.dest_dir, os.path.basename(path)))

        return Ok()
