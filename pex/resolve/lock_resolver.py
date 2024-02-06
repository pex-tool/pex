# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import os.path
import shutil
from collections import OrderedDict
from multiprocessing.pool import ThreadPool

from pex import resolver
from pex.atomic_directory import FileLockStyle
from pex.auth import PasswordDatabase, PasswordEntry
from pex.common import pluralize
from pex.compatibility import cpu_count
from pex.network_configuration import NetworkConfiguration
from pex.orderedset import OrderedSet
from pex.pep_427 import InstallableType
from pex.pep_503 import ProjectName
from pex.pip.local_project import digest_local_project
from pex.pip.tool import PackageIndexConfiguration
from pex.pip.vcs import digest_vcs_archive
from pex.pip.version import PipVersionValue
from pex.resolve.downloads import ArtifactDownloader
from pex.resolve.locked_resolve import (
    DownloadableArtifact,
    FileArtifact,
    LocalProjectArtifact,
    VCSArtifact,
)
from pex.resolve.lockfile.download_manager import DownloadedArtifact, DownloadManager
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.subset import subset
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration, ResolverVersion
from pex.resolve.resolvers import MAX_PARALLEL_DOWNLOADS, Resolver, ResolveResult
from pex.resolver import BuildAndInstallRequest, BuildRequest, InstallRequest
from pex.result import Error, catch, try_
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

    import attr  # vendor:skip

    from pex.hashing import HintedDigest
else:
    from pex.third_party import attr


class FileArtifactDownloadManager(DownloadManager[FileArtifact]):
    def __init__(
        self,
        file_lock_style,  # type: FileLockStyle.Value
        downloader,  # type: ArtifactDownloader
        pex_root=None,  # type: Optional[str]
    ):
        super(FileArtifactDownloadManager, self).__init__(
            pex_root=pex_root, file_lock_style=file_lock_style
        )
        self._downloader = downloader

    def save(
        self,
        artifact,  # type: FileArtifact
        project_name,  # type: ProjectName
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]
        return self._downloader.download(artifact=artifact, dest_dir=dest_dir, digest=digest)


class VCSArtifactDownloadManager(DownloadManager[VCSArtifact]):
    def __init__(
        self,
        target,  # type: Target
        file_lock_style,  # type: FileLockStyle.Value
        indexes=None,  # type: Optional[Sequence[str]]
        find_links=None,  # type: Optional[Sequence[str]]
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
        password_entries=(),  # type: Iterable[PasswordEntry]
        cache=None,  # type: Optional[str]
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        pex_root=None,  # type: Optional[str]
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver=None,  # type: Optional[Resolver]
        use_pip_config=False,  # type: bool
    ):
        super(VCSArtifactDownloadManager, self).__init__(
            pex_root=pex_root, file_lock_style=file_lock_style
        )
        self._target = target
        self._indexes = indexes
        self._find_links = find_links
        self._resolver_version = resolver_version
        self._network_configuration = network_configuration
        self._password_entries = password_entries
        self._cache = cache
        self._build_configuration = attr.evolve(
            build_configuration, allow_wheels=False, prefer_older_binary=False
        )
        self._pip_version = pip_version
        self._resolver = resolver
        self._use_pip_config = use_pip_config

    def save(
        self,
        artifact,  # type: VCSArtifact
        project_name,  # type: ProjectName
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]

        requirement = artifact.as_unparsed_requirement(project_name)
        downloaded_vcs = resolver.download(
            targets=Targets.from_target(self._target),
            requirements=[requirement],
            transitive=False,
            indexes=self._indexes,
            find_links=self._find_links,
            resolver_version=self._resolver_version,
            network_configuration=self._network_configuration,
            password_entries=self._password_entries,
            build_configuration=self._build_configuration,
            max_parallel_jobs=1,
            pip_version=self._pip_version,
            resolver=self._resolver,
            use_pip_config=self._use_pip_config,
        )
        if len(downloaded_vcs.local_distributions) != 1:
            return Error(
                "Expected 1 artifact for an intransitive download of {requirement}, found "
                "{count}:\n"
                "{downloads}".format(
                    requirement=requirement,
                    count=len(downloaded_vcs.local_distributions),
                    downloads="\n".join(
                        "{index}. {download}".format(index=index, download=download.path)
                        for index, download in enumerate(
                            downloaded_vcs.local_distributions, start=1
                        )
                    ),
                )
            )

        local_distribution = downloaded_vcs.local_distributions[0]
        filename = os.path.basename(local_distribution.path)
        digest_vcs_archive(
            archive_path=local_distribution.path,
            vcs=artifact.vcs,
            digest=digest,
        )
        shutil.move(local_distribution.path, os.path.join(dest_dir, filename))
        return filename


class LocalProjectDownloadManager(DownloadManager[LocalProjectArtifact]):
    def __init__(
        self,
        target,  # type: Target
        file_lock_style,  # type: FileLockStyle.Value
        resolver,  # type: Resolver
        pip_version=None,  # type: Optional[PipVersionValue]
        pex_root=None,  # type: Optional[str]
    ):
        super(LocalProjectDownloadManager, self).__init__(
            pex_root=pex_root, file_lock_style=file_lock_style
        )
        self._target = target
        self._pip_version = pip_version
        self._resolver = resolver

    def save(
        self,
        artifact,  # type: LocalProjectArtifact
        project_name,  # type: ProjectName
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]
        source_dir_or_error = digest_local_project(
            directory=artifact.directory,
            digest=digest,
            pip_version=self._pip_version,
            target=self._target,
            resolver=self._resolver,
            dest_dir=dest_dir,
        )
        if isinstance(source_dir_or_error, Error):
            return source_dir_or_error
        return os.path.basename(source_dir_or_error)


def download_artifact(
    downloadable_artifact_and_target,  # type: Tuple[DownloadableArtifact, Target]
    file_download_managers_by_target,  # type: Mapping[Target, FileArtifactDownloadManager]
    vcs_download_managers_by_target,  # type: Mapping[Target, VCSArtifactDownloadManager]
    local_project_download_managers_by_target,  # type: Mapping[Target, LocalProjectDownloadManager]
):
    # type: (...) -> Union[DownloadedArtifact, Error]
    downloadable_artifact, target = downloadable_artifact_and_target
    if isinstance(downloadable_artifact.artifact, VCSArtifact):
        return catch(
            vcs_download_managers_by_target[target].store,
            downloadable_artifact.artifact,
            downloadable_artifact.pin.project_name,
        )

    if isinstance(downloadable_artifact.artifact, FileArtifact):
        return catch(
            file_download_managers_by_target[target].store,
            downloadable_artifact.artifact,
            downloadable_artifact.pin.project_name,
        )

    return catch(
        local_project_download_managers_by_target[target].store,
        downloadable_artifact.artifact,
        downloadable_artifact.pin.project_name,
    )


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
    result_type=InstallableType.INSTALLED_WHEEL_CHROOT,  # type: InstallableType.Value
):
    # type: (...) -> Union[ResolveResult, Error]

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
        )
    )
    downloadable_artifacts_and_targets = OrderedSet(
        (downloadable_artifact, resolved_subset.target)
        for resolved_subset in subset_result.subsets
        for downloadable_artifact in resolved_subset.resolved.downloadable_artifacts
    )

    # Since the download managers are stored to via a thread pool, we need to use BSD style locks.
    # These locks are not as portable as POSIX style locks but work with threading unlike POSIX
    # locks which are subject to threading-unaware deadlock detection per the standard. Linux, in
    # fact, implements deadlock detection for POSIX locks; so we can run afoul of false EDEADLCK
    # errors under the right interleaving of processes and threads and download artifact targets.
    file_lock_style = FileLockStyle.BSD

    file_download_managers_by_target = {
        resolved_subset.target: FileArtifactDownloadManager(
            file_lock_style=file_lock_style,
            downloader=ArtifactDownloader(
                resolver=resolver,
                target=resolved_subset.target,
                package_index_configuration=PackageIndexConfiguration.create(
                    pip_version=pip_version,
                    resolver_version=resolver_version,
                    indexes=indexes,
                    find_links=find_links,
                    network_configuration=network_configuration,
                    password_entries=PasswordDatabase.from_netrc().append(password_entries).entries,
                    use_pip_config=use_pip_config,
                ),
                max_parallel_jobs=max_parallel_jobs,
            ),
        )
        for resolved_subset in subset_result.subsets
    }

    vcs_download_managers_by_target = {
        resolved_subset.target: VCSArtifactDownloadManager(
            target=resolved_subset.target,
            file_lock_style=file_lock_style,
            indexes=indexes,
            find_links=find_links,
            resolver_version=resolver_version,
            network_configuration=network_configuration,
            password_entries=password_entries,
            build_configuration=build_configuration,
            pip_version=pip_version,
            resolver=resolver,
            use_pip_config=use_pip_config,
        )
        for resolved_subset in subset_result.subsets
    }

    local_project_download_managers_by_target = {
        resolved_subset.target: LocalProjectDownloadManager(
            file_lock_style=file_lock_style,
            pip_version=pip_version,
            target=resolved_subset.target,
            resolver=resolver,
        )
        for resolved_subset in subset_result.subsets
    }

    max_threads = min(
        len(downloadable_artifacts_and_targets) or 1,
        min(MAX_PARALLEL_DOWNLOADS, 4 * (max_parallel_jobs or cpu_count() or 1)),
    )
    with TRACER.timed(
        "Downloading {url_count} distributions to satisfy {requirement_count} requirements".format(
            url_count=len(downloadable_artifacts_and_targets),
            requirement_count=len(subset_result.requirements),
        )
    ):
        pool = ThreadPool(processes=max_threads)
        try:
            download_results = tuple(
                zip(
                    tuple(
                        downloadable_artifact
                        for downloadable_artifact, _ in downloadable_artifacts_and_targets
                    ),
                    pool.map(
                        functools.partial(
                            download_artifact,
                            file_download_managers_by_target=file_download_managers_by_target,
                            vcs_download_managers_by_target=vcs_download_managers_by_target,
                            local_project_download_managers_by_target=local_project_download_managers_by_target,
                        ),
                        downloadable_artifacts_and_targets,
                    ),
                )
            )
        finally:
            pool.close()
            pool.join()

    with TRACER.timed("Categorizing {} downloaded artifacts".format(len(download_results))):
        downloaded_artifacts = {}  # type: Dict[DownloadableArtifact, DownloadedArtifact]
        download_errors = OrderedDict()  # type: OrderedDict[DownloadableArtifact, Error]
        for downloadable_artifact, download_result in download_results:
            if isinstance(download_result, DownloadedArtifact):
                downloaded_artifacts[downloadable_artifact] = download_result
            else:
                download_errors[downloadable_artifact] = download_result

        if download_errors:
            error_count = len(download_errors)
            return Error(
                "There {were} {count} {errors} downloading required artifacts:\n"
                "{error_details}".format(
                    were="was" if error_count == 1 else "were",
                    count=error_count,
                    errors=pluralize(download_errors, "error"),
                    error_details="\n".join(
                        "{index}. {pin} from {url}\n    {error}".format(
                            index=index,
                            pin=downloadable_artifact.pin,
                            url=downloadable_artifact.artifact.url.download_url,
                            error=error,
                        )
                        for index, (downloadable_artifact, error) in enumerate(
                            download_errors.items(), start=1
                        )
                    ),
                )
            )

        build_requests = []
        install_requests = []
        for resolved_subset in subset_result.subsets:
            for downloadable_artifact in resolved_subset.resolved.downloadable_artifacts:
                downloaded_artifact = downloaded_artifacts[downloadable_artifact]
                if downloaded_artifact.path.endswith(".whl"):
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
            ),
            compile=compile,
            build_configuration=build_configuration,
            verify_wheels=verify_wheels,
            pip_version=pip_version,
            resolver=resolver,
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
    return ResolveResult(distributions=tuple(distributions), type=result_type)
