# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.auth import PasswordDatabase, PasswordEntry
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Requirement, is_wheel
from pex.network_configuration import NetworkConfiguration
from pex.pep_427 import InstallableType
from pex.pip.tool import PackageIndexConfiguration
from pex.pip.version import PipVersionValue
from pex.resolve.lock_downloader import LockDownloader
from pex.resolve.locked_resolve import LocalProjectArtifact
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.subset import subset
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration, ResolverVersion
from pex.resolve.resolvers import Resolver, ResolveResult
from pex.resolver import BuildAndInstallRequest, BuildRequest, InstallRequest
from pex.result import Error, try_
from pex.targets import Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Sequence, Tuple, Union


def resolve_from_lock(
    targets,  # type: Targets
    lock,  # type: Lockfile
    resolver,  # type: Resolver
    requirements=None,  # type: Optional[Iterable[str]]
    requirement_files=None,  # type: Optional[Iterable[str]]
    constraint_files=None,  # type: Optional[Iterable[str]]
    indexes=None,  # type: Optional[Sequence[str]]
    find_links=None,  # type: Optional[Sequence[str]]
    resolver_version=None,  # type: Optional[ResolverVersion.Value]
    network_configuration=None,  # type: Optional[NetworkConfiguration]
    password_entries=(),  # type: Iterable[PasswordEntry]
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    compile=False,  # type: bool
    transitive=True,  # type: bool
    verify_wheels=True,  # type: bool
    max_parallel_jobs=None,  # type: Optional[int]
    pip_version=None,  # type: Optional[PipVersionValue]
    use_pip_config=False,  # type: bool
    extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
    keyring_provider=None,  # type: Optional[str]
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[ResolveResult, Error]

    dependency_configuration = lock.dependency_configuration().merge(dependency_configuration)
    subset_result = try_(
        subset(
            targets=targets,
            lock=lock,
            requirement_configuration=RequirementConfiguration(
                requirements=requirements,
                requirement_files=requirement_files,
                constraint_files=constraint_files,
            ),
            network_configuration=network_configuration,
            build_configuration=build_configuration,
            transitive=transitive,
            dependency_configuration=dependency_configuration,
        )
    )
    downloadable_artifacts_and_targets = tuple(
        (downloadable_artifact, resolved_subset.target)
        for resolved_subset in subset_result.subsets
        for downloadable_artifact in resolved_subset.resolved.downloadable_artifacts
    )

    lock_downloader = LockDownloader.create(
        targets=tuple(resolved_subset.target for resolved_subset in subset_result.subsets),
        lock=lock,
        resolver=resolver,
        indexes=indexes,
        find_links=find_links,
        max_parallel_jobs=max_parallel_jobs,
        pip_version=pip_version,
        resolver_version=resolver_version,
        network_configuration=network_configuration,
        password_entries=password_entries,
        build_configuration=build_configuration,
        use_pip_config=use_pip_config,
        extra_pip_requirements=extra_pip_requirements,
        keyring_provider=keyring_provider,
    )
    with TRACER.timed(
        "Downloading {url_count} distributions to satisfy {requirement_count} requirements".format(
            url_count=len(downloadable_artifacts_and_targets),
            requirement_count=len(subset_result.requirements),
        )
    ):
        downloaded_artifacts = lock_downloader.download_artifacts(
            downloadable_artifacts_and_targets
        )
        if isinstance(downloaded_artifacts, Error):
            return downloaded_artifacts

    with TRACER.timed("Categorizing {} downloaded artifacts".format(len(downloaded_artifacts))):
        build_requests = []
        install_requests = []
        for resolved_subset in subset_result.subsets:
            for downloadable_artifact in resolved_subset.resolved.downloadable_artifacts:
                downloaded_artifact = downloaded_artifacts[downloadable_artifact]
                if is_wheel(downloaded_artifact.path):
                    install_requests.append(
                        InstallRequest(
                            target=resolved_subset.target,
                            wheel_path=downloaded_artifact.path,
                            fingerprint=downloaded_artifact.fingerprint,
                        )
                    )
                else:
                    build_requests.append(
                        BuildRequest(
                            target=resolved_subset.target,
                            source_path=downloaded_artifact.path,
                            fingerprint=downloaded_artifact.fingerprint,
                        )
                    )

    with TRACER.timed(
        "Building {} artifacts and installing {}".format(
            len(build_requests), len(build_requests) + len(install_requests)
        )
    ):
        build_and_install_request = BuildAndInstallRequest(
            build_requests=build_requests,
            install_requests=install_requests,
            direct_requirements=subset_result.requirements,
            package_index_configuration=PackageIndexConfiguration.create(
                pip_version=pip_version,
                resolver_version=resolver_version,
                indexes=indexes,
                find_links=find_links,
                network_configuration=network_configuration,
                password_entries=PasswordDatabase.from_netrc().append(password_entries).entries,
                use_pip_config=use_pip_config,
                extra_pip_requirements=extra_pip_requirements,
                keyring_provider=keyring_provider,
            ),
            compile=compile,
            build_configuration=build_configuration,
            verify_wheels=verify_wheels,
            pip_version=pip_version,
            resolver=resolver,
            dependency_configuration=dependency_configuration,
        )

        local_project_directory_to_sdist = {
            downloadable_artifact.artifact.directory: downloaded_artifact.path
            for downloadable_artifact, downloaded_artifact in downloaded_artifacts.items()
            if isinstance(downloadable_artifact.artifact, LocalProjectArtifact)
        }

        # This otherwise checks that resolved distributions all meet internal requirement
        # constraints (This allows pip-legacy-resolver resolves with invalid solutions to be
        # failed post-facto by Pex at PEX build time). We've already done this via
        # `LockedResolve.resolve` above and need not waste time (~O(100ms)) doing this again.
        ignore_errors = True

        distributions = (
            build_and_install_request.install_distributions(
                ignore_errors=ignore_errors,
                max_parallel_jobs=max_parallel_jobs,
                local_project_directory_to_sdist=local_project_directory_to_sdist,
            )
            if result_type is InstallableType.INSTALLED_WHEEL_CHROOT
            else build_and_install_request.build_distributions(
                ignore_errors=ignore_errors,
                max_parallel_jobs=max_parallel_jobs,
                local_project_directory_to_sdist=local_project_directory_to_sdist,
            )
        )
    return ResolveResult(
        dependency_configuration=dependency_configuration,
        distributions=tuple(distributions),
        type=result_type,
    )
