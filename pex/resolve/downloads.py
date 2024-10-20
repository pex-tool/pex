# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil

from pex import hashing
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir, DownloadDir
from pex.common import safe_mkdir, safe_mkdtemp
from pex.hashing import Sha256
from pex.jobs import Job, Raise, SpawnedJob, execute_parallel
from pex.pip import foreign_platform
from pex.pip.download_observer import DownloadObserver
from pex.pip.installation import get_pip
from pex.pip.tool import PackageIndexConfiguration, Pip
from pex.resolve import locker
from pex.resolve.locked_resolve import Artifact, FileArtifact, LockConfiguration
from pex.resolve.resolved_requirement import ArtifactURL, Fingerprint, PartialArtifact
from pex.resolve.resolvers import Resolver
from pex.result import Error
from pex.targets import LocalInterpreter, Target
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Optional, Union

    import attr  # vendor:skip

    from pex.hashing import HintedDigest
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class ArtifactDownloader(object):
    resolver = attr.ib()  # type: Resolver
    lock_configuration = attr.ib()  # type: LockConfiguration
    target = attr.ib(factory=LocalInterpreter.create)  # type: Target
    package_index_configuration = attr.ib(
        factory=PackageIndexConfiguration.create
    )  # type: PackageIndexConfiguration
    max_parallel_jobs = attr.ib(default=None)  # type: Optional[int]
    pip = attr.ib(init=False)  # type: Pip

    @pip.default
    def _pip(self):
        return get_pip(
            interpreter=self.target.get_interpreter(),
            version=self.package_index_configuration.pip_version,
            resolver=self.resolver,
            extra_requirements=self.package_index_configuration.extra_pip_requirements,
        )

    @staticmethod
    def _fingerprint_and_move(path):
        # type: (str) -> Fingerprint
        digest = Sha256()
        hashing.file_hash(path, digest)
        fingerprint = digest.hexdigest()
        target_dir = DownloadDir.create(file_hash=fingerprint)
        with atomic_directory(target_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                shutil.move(path, os.path.join(atomic_dir.work_dir, os.path.basename(path)))
        return Fingerprint.from_hashing_fingerprint(fingerprint)

    @staticmethod
    def _create_file_artifact(
        url,  # type: ArtifactURL
        fingerprint,  # type: Fingerprint
        verified,  # type: bool
    ):
        # type: (...) -> FileArtifact
        fingerprinted_artifact = Artifact.from_artifact_url(url, fingerprint, verified=verified)
        if not isinstance(fingerprinted_artifact, FileArtifact):
            raise ValueError(
                "Expected a file artifact, given url {url} which is a {artifact}.".format(
                    url=url, artifact=fingerprinted_artifact
                )
            )
        return fingerprinted_artifact

    def _download(
        self,
        url,  # type: ArtifactURL
        download_dir,  # type: str
    ):
        # type: (...) -> Job

        download_url = url.download_url
        for password_entry in self.package_index_configuration.password_entries:
            credentialed_url = password_entry.maybe_inject_in_url(download_url)
            if credentialed_url:
                download_url = credentialed_url
                break

        # Although we don't actually need to observe the download, we do need to patch Pip to not
        # care about wheel tags, environment markers or Requires-Python if the lock target is
        # either foreign or universal. The locker.patch below handles the universal case or else
        # generates no patches if the lock is not universal.
        download_observer = foreign_platform.patch(self.target) or DownloadObserver(
            analyzer=None,
            patch_set=locker.patch(lock_configuration=self.lock_configuration),
        )
        return self.pip.spawn_download_distributions(
            download_dir=download_dir,
            requirements=[download_url],
            transitive=False,
            package_index_configuration=self.package_index_configuration,
            observer=download_observer,
        )

    def _download_and_fingerprint(self, url):
        # type: (ArtifactURL) -> SpawnedJob[FileArtifact]
        download_dir = safe_mkdtemp(
            prefix="fingerprint_artifact.", dir=safe_mkdir(CacheDir.DOWNLOADS.path(".tmp"))
        )

        src_file = url.path
        temp_dest = os.path.join(download_dir, os.path.basename(src_file))

        if url.scheme == "file":
            shutil.copy(src_file, temp_dest)
            return SpawnedJob.completed(
                self._create_file_artifact(
                    url, fingerprint=self._fingerprint_and_move(temp_dest), verified=True
                )
            )

        return SpawnedJob.and_then(
            self._download(url=url, download_dir=download_dir),
            result_func=lambda: self._create_file_artifact(
                url, fingerprint=self._fingerprint_and_move(temp_dest), verified=True
            ),
        )

    def _to_file_artifact(self, artifact):
        # type: (PartialArtifact) -> SpawnedJob[FileArtifact]
        url = artifact.url
        fingerprint = artifact.fingerprint
        if fingerprint:
            return SpawnedJob.completed(
                self._create_file_artifact(url, fingerprint, verified=artifact.verified)
            )
        return self._download_and_fingerprint(url)

    def fingerprint(self, artifacts):
        # type: (Iterable[PartialArtifact]) -> Iterator[FileArtifact]
        return execute_parallel(
            inputs=artifacts,
            spawn_func=self._to_file_artifact,
            error_handler=Raise[PartialArtifact, FileArtifact](IOError),
        )

    def download(
        self,
        artifact,  # type: FileArtifact
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]
        dest_file = os.path.join(dest_dir, artifact.filename)

        if artifact.url.scheme == "file":
            src_file = artifact.url.path
            try:
                shutil.copy(src_file, dest_file)
            except (IOError, OSError) as e:
                return Error(str(e))
        else:
            try:
                self._download(url=artifact.url, download_dir=dest_dir).wait()
            except Job.Error as e:
                error_lines = list(e.contextualized_stderr()) or str(e).splitlines()
                return Error(
                    os.linesep.join(error_lines)
                    if "See above for details" in error_lines[-1]
                    else error_lines[-1]
                )
        hashing.file_hash(dest_file, digest)
        return artifact.filename
