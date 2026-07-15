# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
from collections import OrderedDict
from multiprocessing.pool import ThreadPool

from pex import hashing, resolver, sdist
from pex.auth import PasswordDatabase
from pex.common import pluralize, safe_mkdtemp
from pex.compatibility import cpu_count
from pex.dist_metadata import Requirement, is_sdist
from pex.network_configuration import NetworkConfiguration
from pex.pep_503 import ProjectName
from pex.pip.local_project import digest_local_project
from pex.pip.tool import PackageIndexConfiguration
from pex.pip.vcs import digest_vcs_archive, find_vcs_archive
from pex.pip.version import PipVersionValue
from pex.requirements import parse_requirement_string
from pex.resolve.downloads import ArtifactDownloader
from pex.resolve.locked_resolve import (
    DownloadableArtifact,
    FileArtifact,
    LocalProjectArtifact,
    LockConfiguration,
    UnFingerprintedLocalProjectArtifact,
    UnFingerprintedVCSArtifact,
    VCSArtifact,
)
from pex.resolve.lockfile.download_manager import DownloadedArtifact, DownloadManager
from pex.resolve.package_repository import ReposConfiguration
from pex.resolve.resolver_configuration import BuildConfiguration, ResolverVersion
from pex.resolve.resolvers import MAX_PARALLEL_DOWNLOADS, Resolver
from pex.result import Error, ResultError, catch, try_
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
        downloader,  # type: ArtifactDownloader
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        super(FileArtifactDownloadManager, self).__init__(pex_root=pex_root)
        self._downloader = downloader

    def digest(
        self,
        artifact,  # type: FileArtifact
        project_name,  # type: ProjectName
        download_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> str
        hashing.file_hash(path=os.path.join(download_dir, artifact.filename), digest=digest)
        return artifact.filename

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
        repos_configuration=ReposConfiguration(),  # type: ReposConfiguration
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
        cache=None,  # type: Optional[str]
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        pex_root=ENV,  # type: Union[str, Variables]
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver=None,  # type: Optional[Resolver]
        use_pip_config=False,  # type: bool
        extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
        keyring_provider=None,  # type: Optional[str]
    ):
        super(VCSArtifactDownloadManager, self).__init__(pex_root=pex_root)
        self._target = target
        self._repos_configuration = repos_configuration
        self._resolver_version = resolver_version
        self._network_configuration = network_configuration
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

    def digest(
        self,
        artifact,  # type: Union[UnFingerprintedVCSArtifact, VCSArtifact]
        project_name,  # type: ProjectName
        download_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> str

        archive_path = try_(find_vcs_archive(download_dir))
        digest_vcs_archive(
            project_name=project_name,
            archive_path=archive_path,
            vcs=artifact.vcs,
            digest=digest,
        )
        return os.path.basename(archive_path)

    def save(
        self,
        artifact,  # type: Union[UnFingerprintedVCSArtifact, VCSArtifact]
        project_name,  # type: ProjectName
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]

        requirement = artifact.as_unparsed_requirement(project_name)
        downloaded_vcs = resolver.download(
            targets=Targets.from_target(self._target),
            requirements=[parse_requirement_string(requirement)],
            transitive=False,
            repos_configuration=self._repos_configuration,
            resolver_version=self._resolver_version,
            network_configuration=self._network_configuration,
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
            project_name=project_name,
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
        resolver,  # type: Resolver
        pip_version=None,  # type: Optional[PipVersionValue]
        pex_root=ENV,  # type: Union[str, Variables]
    ):
        super(LocalProjectDownloadManager, self).__init__(pex_root=pex_root)
        self._target = target
        self._pip_version = pip_version
        self._resolver = resolver

    def digest(
        self,
        artifact,  # type: Union[LocalProjectArtifact, UnFingerprintedLocalProjectArtifact]
        project_name,  # type: ProjectName
        download_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> str

        sdists = [path for path in os.listdir(download_dir) if is_sdist(path)]
        if not sdists:
            raise ResultError(
                Error(
                    "Found no project source distribution for {project_name} in download directory "
                    "{download_dir}.".format(project_name=project_name, download_dir=download_dir)
                )
            )
        if len(sdists) > 1:
            raise ResultError(
                Error(
                    "Found more than one potential project source distribution for {project_name} "
                    "in download directory {download_dir}:\n"
                    "{sdists}".format(
                        project_name=project_name,
                        download_dir=download_dir,
                        sdists="\n".join(
                            "{idx}. {directory}".format(idx=idx, directory=directory)
                            for idx, directory in enumerate(sdists, start=1)
                        ),
                    )
                )
            )
        sdist_path = os.path.join(download_dir, sdists[0])

        project_dir = sdist.extract_tarball(sdist_path, dest_dir=safe_mkdtemp())
        hashing.dir_hash(directory=project_dir, digest=digest)
        return os.path.basename(sdist_path)

    def save(
        self,
        artifact,  # type: Union[LocalProjectArtifact, UnFingerprintedLocalProjectArtifact]
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
        lock_configuration,  # type: LockConfiguration
        resolver,  # type: Resolver
        repos_configuration=ReposConfiguration(),  # type: ReposConfiguration
        max_parallel_jobs=None,  # type: Optional[int]
        pip_version=None,  # type: Optional[PipVersionValue]
        resolver_version=None,  # type: Optional[ResolverVersion.Value]
        network_configuration=None,  # type: Optional[NetworkConfiguration]
        build_configuration=BuildConfiguration(),  # type: BuildConfiguration
        use_pip_config=False,  # type: bool
        extra_pip_requirements=(),  # type: Tuple[Requirement, ...]
        keyring_provider=None,  # type: Optional[str]
    ):
        # type: (...) -> LockDownloader

        password_database = PasswordDatabase.from_netrc().append(
            repos_configuration.password_entries
        )
        repos_configuration = attr.evolve(
            repos_configuration, password_entries=password_database.entries
        )
        file_download_managers_by_target = {
            target: FileArtifactDownloadManager(
                downloader=ArtifactDownloader(
                    resolver=resolver,
                    universal_target=lock_configuration.universal_target,
                    target=target,
                    package_index_configuration=PackageIndexConfiguration.create(
                        pip_version=pip_version,
                        resolver_version=resolver_version,
                        repos_configuration=repos_configuration,
                        network_configuration=network_configuration,
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
                repos_configuration=repos_configuration,
                resolver_version=resolver_version,
                network_configuration=network_configuration,
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
        if isinstance(downloadable_artifact.artifact, (UnFingerprintedVCSArtifact, VCSArtifact)):
            return catch(
                self.vcs_download_managers_by_target[target].store,
                downloadable_artifact.artifact,
                downloadable_artifact.project_name,
            )

        if isinstance(downloadable_artifact.artifact, FileArtifact):
            return catch(
                self.file_download_managers_by_target[target].store,
                downloadable_artifact.artifact,
                downloadable_artifact.project_name,
            )

        return catch(
            self.local_project_download_managers_by_target[target].store,
            downloadable_artifact.artifact,
            downloadable_artifact.project_name,
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
                        "{index}. {spec} from {url}\n    {error}".format(
                            index=index,
                            spec=downloadable_artifact.specifier(),
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
