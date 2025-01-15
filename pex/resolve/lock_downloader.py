# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
from collections import OrderedDict
from multiprocessing.pool import ThreadPool

from pex import resolver
from pex.atomic_directory import FileLockStyle
from pex.auth import PasswordDatabase, PasswordEntry
from pex.common import pluralize
from pex.compatibility import cpu_count
from pex.dist_metadata import Requirement
from pex.network_configuration import NetworkConfiguration
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
from pex.resolve.resolver_configuration import BuildConfiguration, ResolverVersion
from pex.resolve.resolvers import MAX_PARALLEL_DOWNLOADS, Resolver
from pex.result import Error, catch
from pex.targets import Target, Targets
from pex.typing import TYPE_CHECKING
from pex.variables import ENV, Variables

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
        pex_root=ENV,  # type: Union[str, Variables]
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
        pex_root=ENV,  # type: Union[str, Variables]
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver=None,  # type: Optional[Resolver]
        use_pip_config=False,  # type: bool
        extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
        keyring_provider=None,  # type: Optional[str]
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

        # Since a VCSArtifactDownloadManager is only used for VCS requirements, a build is both
        # required and preferred by the user.
        self._build_configuration = attr.evolve(
            build_configuration, allow_builds=True, prefer_older_binary=False
        )

        self._pip_version = pip_version
        self._resolver = resolver
        self._use_pip_config = use_pip_config
        self._extra_pip_requirements = extra_pip_requirements
        self._keyring_provider = keyring_provider

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
            extra_pip_requirements=self._extra_pip_requirements,
            keyring_provider=self._keyring_provider,
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
        pex_root=ENV,  # type: Union[str, Variables]
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


@attr.s(frozen=True)
class LockDownloader(object):
    @classmethod
    def create(
        cls,
        targets,  # type: Iterable[Target]
        lock,  # type: Lockfile
        resolver,  # type: Resolver
        indexes=None,  # type: Optional[Sequence[str]]
        find_links=None,  # type: Optional[Sequence[str]]
        max_parallel_jobs=None,  # type: Optional[int]
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
        password_entries=(),  # type: Iterable[PasswordEntry]
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        use_pip_config=False,  # type: bool
        extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
        keyring_provider=None,  # type: Optional[str]
    ):
        # type: (...) -> LockDownloader

        # Since the download managers are stored to via a thread pool, we need to use BSD style locks.
        # These locks are not as portable as POSIX style locks but work with threading unlike POSIX
        # locks which are subject to threading-unaware deadlock detection per the standard. Linux, in
        # fact, implements deadlock detection for POSIX locks; so we can run afoul of false EDEADLCK
        # errors under the right interleaving of processes and threads and download artifact targets.
        file_lock_style = FileLockStyle.BSD

        file_download_managers_by_target = {
            target: FileArtifactDownloadManager(
                file_lock_style=file_lock_style,
                downloader=ArtifactDownloader(
                    resolver=resolver,
                    lock_configuration=lock.lock_configuration(),
                    target=target,
                    package_index_configuration=PackageIndexConfiguration.create(
                        pip_version=pip_version,
                        resolver_version=resolver_version,
                        indexes=indexes,
                        find_links=find_links,
                        network_configuration=network_configuration,
                        password_entries=(
                            PasswordDatabase.from_netrc().append(password_entries).entries
                        ),
                        use_pip_config=use_pip_config,
                        extra_pip_requirements=extra_pip_requirements,
                        keyring_provider=keyring_provider,
                    ),
                    max_parallel_jobs=max_parallel_jobs,
                ),
            )
            for target in targets
        }

        vcs_download_managers_by_target = {
            target: VCSArtifactDownloadManager(
                target=target,
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
                extra_pip_requirements=extra_pip_requirements,
                keyring_provider=keyring_provider,
            )
            for target in targets
        }

        local_project_download_managers_by_target = {
            target: LocalProjectDownloadManager(
                file_lock_style=file_lock_style,
                pip_version=pip_version,
                target=target,
                resolver=resolver,
            )
            for target in targets
        }

        return cls(
            file_download_managers_by_target,
            vcs_download_managers_by_target,
            local_project_download_managers_by_target,
            max_parallel_jobs,
        )

    file_download_managers_by_target = (
        attr.ib()
    )  # type: Mapping[Target, FileArtifactDownloadManager]
    vcs_download_managers_by_target = attr.ib()  # type: Mapping[Target, VCSArtifactDownloadManager]
    local_project_download_managers_by_target = (
        attr.ib()
    )  # type: Mapping[Target, LocalProjectDownloadManager]
    max_parallel_jobs = attr.ib(default=None)  # type: Optional[int]

    def download_artifact(self, downloadable_artifact_and_target):
        # type: (Tuple[DownloadableArtifact, Target]) -> Union[DownloadedArtifact, Error]
        downloadable_artifact, target = downloadable_artifact_and_target
        if isinstance(downloadable_artifact.artifact, VCSArtifact):
            return catch(
                self.vcs_download_managers_by_target[target].store,
                downloadable_artifact.artifact,
                downloadable_artifact.pin.project_name,
            )

        if isinstance(downloadable_artifact.artifact, FileArtifact):
            return catch(
                self.file_download_managers_by_target[target].store,
                downloadable_artifact.artifact,
                downloadable_artifact.pin.project_name,
            )

        return catch(
            self.local_project_download_managers_by_target[target].store,
            downloadable_artifact.artifact,
            downloadable_artifact.pin.project_name,
        )

    def download_artifacts(self, downloadable_artifacts_and_targets):
        # type: (Sequence[Tuple[DownloadableArtifact, Target]]) -> Union[Dict[DownloadableArtifact, DownloadedArtifact], Error]
        max_threads = min(
            len(downloadable_artifacts_and_targets) or 1,
            min(MAX_PARALLEL_DOWNLOADS, 4 * (self.max_parallel_jobs or cpu_count() or 1)),
        )
        pool = ThreadPool(processes=max_threads)
        try:
            download_results = tuple(
                zip(
                    tuple(
                        downloadable_artifact
                        for downloadable_artifact, _ in downloadable_artifacts_and_targets
                    ),
                    pool.map(self.download_artifact, downloadable_artifacts_and_targets),
                )
            )
        finally:
            pool.close()
            pool.join()

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
                            error="\n    ".join(str(error).splitlines()),
                        )
                        for index, (downloadable_artifact, error) in enumerate(
                            download_errors.items(), start=1
                        )
                    ),
                )
            )

        return downloaded_artifacts
