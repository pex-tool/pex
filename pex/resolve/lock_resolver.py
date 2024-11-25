# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os
import tarfile
from collections import OrderedDict, defaultdict

from pex.auth import PasswordDatabase, PasswordEntry
from pex.build_system import BuildSystem, BuildSystemTable
from pex.cache.dirs import CacheDir
from pex.common import open_zip, safe_mkdtemp
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import Distribution, Requirement, is_sdist, is_tar_sdist, is_wheel
from pex.exceptions import production_assert
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.interpreter import PythonInterpreter
from pex.network_configuration import NetworkConfiguration
from pex.pep_427 import InstallableType, install_wheel_chroot
from pex.pip.tool import PackageIndexConfiguration
from pex.pip.version import PipVersionValue
from pex.resolve.lock_downloader import LockDownloader
from pex.resolve.locked_resolve import (
    DownloadableArtifact,
    LocalProjectArtifact,
    LockedResolve,
    Resolved,
)
from pex.resolve.lockfile.download_manager import DownloadedArtifact
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.subset import subset, subset_for_target
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration, ResolverVersion
from pex.resolve.resolvers import ResolvedDistribution, Resolver, ResolveResult
from pex.resolver import BuildAndInstallRequest, BuildRequest, InstallRequest
from pex.result import Error, try_
from pex.sorted_tuple import SortedTuple
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import DefaultDict, Dict, Iterable, List, Optional, Sequence, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class LockedSourceDistribution(object):
    target = attr.ib()  # type: Target
    source_artifact = attr.ib()  # type: DownloadedArtifact
    build_system_table = attr.ib()  # type: BuildSystemTable
    locked_resolves = attr.ib()  # type: Tuple[LockedResolve, ...]


def build_locked_source_distribution(
    locked_source_distribution,  # type: LockedSourceDistribution
    install_requests,  # type: Iterable[InstallRequest]
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
):
    # type: (...) -> Union[ResolvedDistribution, Error]

    installed_wheels_dir = CacheDir.INSTALLED_WHEELS.path()
    build_system_distributions = []  # type: List[Distribution]
    for install_request in install_requests:
        install_result = install_request.result(installed_wheels_dir)
        installed_wheel = install_wheel_chroot(
            wheel_path=install_request.wheel_path, destination=install_result.build_chroot
        )
        build_system_distributions.append(Distribution.load(installed_wheel.prefix_dir))

    result = BuildSystem.create(
        interpreter=PythonInterpreter.get(),
        requires=locked_source_distribution.build_system_table.requires,
        resolved=build_system_distributions,
        build_backend=locked_source_distribution.build_system_table.build_backend,
        backend_path=locked_source_distribution.build_system_table.backend_path,
    )
    if isinstance(result, Error):
        return result

    source_artifact_path = locked_source_distribution.source_artifact.path
    if is_sdist(source_artifact_path):
        chroot = safe_mkdtemp()
        if is_tar_sdist(source_artifact_path):
            with tarfile.open(source_artifact_path) as tar_fp:
                tar_fp.extractall(chroot)
        else:
            with open_zip(source_artifact_path) as zip_fp:
                zip_fp.extractall(chroot)
        for root, _, files in os.walk(chroot, topdown=True):
            if any(f in ("setup.py", "setup.cfg", "pyproject.toml") for f in files):
                project_directory = root
                break
        else:
            return Error("TODO(John Sirois): XXX: Can't happen!")
    else:
        project_directory = source_artifact_path

    build_dir = os.path.join(safe_mkdtemp(), "build")
    os.mkdir(build_dir)
    spawned_job = try_(
        result.invoke_build_hook(
            project_directory,
            hook_method="build_wheel",
            hook_args=[build_dir],
        )
    )
    distribution = spawned_job.map(lambda _: Distribution.load(build_dir)).await_result()
    build_wheel_fingerprint = CacheHelper.hash(distribution.location, hasher=hashlib.sha256)
    if result_type is InstallableType.INSTALLED_WHEEL_CHROOT:
        install_request = InstallRequest(
            target=locked_source_distribution.target,
            wheel_path=distribution.location,
            fingerprint=build_wheel_fingerprint,
        )
        install_result = install_request.result(installed_wheels_dir)
        installed_wheel = install_wheel_chroot(
            wheel_path=install_request.wheel_path, destination=install_result.build_chroot
        )
        distribution = Distribution.load(installed_wheel.prefix_dir)

    return ResolvedDistribution(
        target=locked_source_distribution.target,
        fingerprinted_distribution=FingerprintedDistribution(
            distribution=distribution, fingerprint=build_wheel_fingerprint
        ),
        direct_requirements=SortedTuple(),
    )


def build_locked_source_distributions(
    locked_source_distributions,  # type: Sequence[LockedSourceDistribution]
    lock_downloader,  # type: LockDownloader
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
    build_configuration=BuildConfiguration(),  # type: BuildConfiguration
    dependency_configuration=DependencyConfiguration(),  # type: DependencyConfiguration
):
    # type: (...) -> Union[Iterable[ResolvedDistribution], Error]

    downloadable_artifacts_by_locked_source_distribution = (
        {}
    )  # type: Dict[LockedSourceDistribution, Tuple[DownloadableArtifact, ...]]
    subset_errors = OrderedDict()  # type: OrderedDict[LockedSourceDistribution, Tuple[Error, ...]]
    for locked_source_distribution in locked_source_distributions:
        subset_result = subset_for_target(
            target=locked_source_distribution.target,
            locked_resolves=locked_source_distribution.locked_resolves,
            requirements_to_resolve=tuple(
                Requirement.parse(req)
                for req in locked_source_distribution.build_system_table.requires
            ),
            build_configuration=build_configuration,
            dependency_configuration=dependency_configuration,
        )
        if isinstance(subset_result, Resolved):
            downloadable_artifacts_by_locked_source_distribution[
                locked_source_distribution
            ] = subset_result.downloadable_artifacts
        elif isinstance(subset_result, tuple) and subset_result:
            subset_errors[locked_source_distribution] = subset_result
    if subset_errors:
        return Error("TODO(John Sirois): XXX: build a subset errors message")

    downloaded_artifacts = try_(
        lock_downloader.download_artifacts(
            tuple(
                (downloadable_artifact, locked_source_distribution.target)
                for locked_source_distribution, downloadable_artifacts in downloadable_artifacts_by_locked_source_distribution.items()
                for downloadable_artifact in downloadable_artifacts
            )
        )
    )
    install_requests_by_locked_source_distribution = defaultdict(
        list
    )  # type: DefaultDict[LockedSourceDistribution, List[InstallRequest]]
    resolve_errors = defaultdict(
        list
    )  # type: DefaultDict[LockedSourceDistribution, List[DownloadedArtifact]]
    for (
        locked_source_distribution,
        downloadable_artifacts,
    ) in downloadable_artifacts_by_locked_source_distribution.items():
        for downloadable_artifact in downloadable_artifacts:
            downloaded_artifact = downloaded_artifacts[downloadable_artifact]
            if is_wheel(downloaded_artifact.path):
                install_requests_by_locked_source_distribution[locked_source_distribution].append(
                    InstallRequest(
                        target=locked_source_distribution.target,
                        wheel_path=downloaded_artifact.path,
                        fingerprint=downloaded_artifact.fingerprint,
                    )
                )
            else:
                resolve_errors[locked_source_distribution].append(downloaded_artifact)
    if resolve_errors:
        return Error("TODO(John Sirois): XXX: build a resolve errors message")

    # TODO(John Sirois): now we have a list of install requests needed per each source distribution
    #  build system, parallelize install + create pip venv + build wheel
    built_distributions = []  # type: List[ResolvedDistribution]
    build_errors = []  # type: List[Error]
    for (
        locked_source_distribution,
        install_requests,
    ) in install_requests_by_locked_source_distribution.items():
        build_result = build_locked_source_distribution(
            locked_source_distribution, install_requests, result_type
        )
        if isinstance(build_result, ResolvedDistribution):
            built_distributions.append(build_result)
        else:
            build_errors.append(build_result)
    if build_errors:
        return Error("TODO(John Sirois): XXX: build a build errors message")
    return built_distributions


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
        build_requests = []  # type: List[BuildRequest]
        locked_build_requests = []  # type: List[LockedSourceDistribution]
        install_requests = []  # type: List[InstallRequest]
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
                elif lock.lock_build_systems:
                    production_assert(downloadable_artifact.build_system_table is not None)
                    build_system_table = cast(
                        BuildSystemTable, downloadable_artifact.build_system_table
                    )
                    locked_build_system_resolves = lock.build_systems[build_system_table]
                    locked_build_requests.append(
                        LockedSourceDistribution(
                            target=resolved_subset.target,
                            source_artifact=downloaded_artifact,
                            build_system_table=build_system_table,
                            locked_resolves=locked_build_system_resolves,
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
        build_request_count = len(build_requests)
        locked_build_request_count = len(locked_build_requests)
        production_assert(
            ((build_request_count > 0) ^ (locked_build_request_count > 0))
            or (build_request_count == 0 and locked_build_request_count == 0)
        )

    with TRACER.timed(
        "Building {} artifacts and installing {}".format(
            build_request_count, build_request_count + len(install_requests)
        )
    ):
        distributions = list(
            try_(
                build_locked_source_distributions(
                    locked_build_requests,
                    lock_downloader,
                    result_type=result_type,
                    build_configuration=build_configuration,
                    dependency_configuration=dependency_configuration,
                )
            )
        )

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

        distributions.extend(
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
