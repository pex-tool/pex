# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.pep_427 import InstallableType
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.lock_resolver import resolve_from_lock
from pex.resolve.pex_repository_resolver import resolve_from_pex
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import (
    LockRepositoryConfiguration,
    PexRepositoryConfiguration,
)
from pex.resolve.resolvers import ResolveResult
from pex.resolver import resolve as resolve_via_pip
from pex.result import try_
from pex.targets import Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pex.resolve.resolver_options import ResolverConfiguration


def resolve(
    targets,  # type: Targets
    requirement_configuration,  # type: RequirementConfiguration
    resolver_configuration,  # type: ResolverConfiguration
    compile_pyc=False,  # type: bool
    ignore_errors=False,  # type: bool
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
):
    # type: (...) -> ResolveResult
    if isinstance(resolver_configuration, LockRepositoryConfiguration):
        lock = try_(resolver_configuration.parse_lock())
        with TRACER.timed(
            "Resolving requirements from lock file {lock_file}".format(lock_file=lock.source)
        ):
            pip_configuration = resolver_configuration.pip_configuration
            return try_(
                resolve_from_lock(
                    targets=targets,
                    lock=lock,
                    resolver=ConfiguredResolver(pip_configuration=pip_configuration),
                    requirements=requirement_configuration.requirements,
                    requirement_files=requirement_configuration.requirement_files,
                    constraint_files=requirement_configuration.constraint_files,
                    transitive=pip_configuration.transitive,
                    indexes=pip_configuration.repos_configuration.indexes,
                    find_links=pip_configuration.repos_configuration.find_links,
                    resolver_version=pip_configuration.resolver_version,
                    network_configuration=pip_configuration.network_configuration,
                    password_entries=pip_configuration.repos_configuration.password_entries,
                    build_configuration=pip_configuration.build_configuration,
                    compile=compile_pyc,
                    max_parallel_jobs=pip_configuration.max_jobs,
                    pip_version=lock.pip_version,
                    use_pip_config=pip_configuration.use_pip_config,
                    result_type=result_type,
                )
            )
    elif isinstance(resolver_configuration, PexRepositoryConfiguration):
        with TRACER.timed(
            "Resolving requirements from PEX {pex_repository}.".format(
                pex_repository=resolver_configuration.pex_repository
            )
        ):
            return resolve_from_pex(
                targets=targets,
                pex=resolver_configuration.pex_repository,
                requirements=requirement_configuration.requirements,
                requirement_files=requirement_configuration.requirement_files,
                constraint_files=requirement_configuration.constraint_files,
                network_configuration=resolver_configuration.network_configuration,
                transitive=resolver_configuration.transitive,
                ignore_errors=ignore_errors,
                result_type=result_type,
            )
    else:
        with TRACER.timed("Resolving requirements."):
            return resolve_via_pip(
                targets=targets,
                requirements=requirement_configuration.requirements,
                requirement_files=requirement_configuration.requirement_files,
                constraint_files=requirement_configuration.constraint_files,
                allow_prereleases=resolver_configuration.allow_prereleases,
                transitive=resolver_configuration.transitive,
                indexes=resolver_configuration.repos_configuration.indexes,
                find_links=resolver_configuration.repos_configuration.find_links,
                resolver_version=resolver_configuration.resolver_version,
                network_configuration=resolver_configuration.network_configuration,
                password_entries=resolver_configuration.repos_configuration.password_entries,
                build_configuration=resolver_configuration.build_configuration,
                compile=compile_pyc,
                max_parallel_jobs=resolver_configuration.max_jobs,
                ignore_errors=ignore_errors,
                preserve_log=resolver_configuration.preserve_log,
                pip_version=resolver_configuration.version,
                resolver=ConfiguredResolver(pip_configuration=resolver_configuration),
                use_pip_config=resolver_configuration.use_pip_config,
                result_type=result_type,
            )
