from __future__ import absolute_import

import os.path
import shutil

from pex import hashing
from pex.common import atomic_directory, safe_mkdir, safe_mkdtemp
from pex.compatibility import urlparse
from pex.hashing import Sha256
from pex.jobs import Job, Raise, SpawnedJob, execute_parallel
from pex.pip.tool import PackageIndexConfiguration, Pip, get_pip
from pex.resolve.locked_resolve import Artifact, FileArtifact
from pex.resolve.resolved_requirement import Fingerprint, PartialArtifact
from pex.result import Error
from pex.targets import LocalInterpreter, Target
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Dict, Iterable, Iterator, Optional, Union

    import attr  # vendor:skip

    from pex.hashing import HintedDigest
else:
    from pex.third_party import attr


_DOWNLOADS_DIRS = {}  # type: Dict[str, str]


def get_downloads_dir(pex_root=None):
    # type: (Optional[str]) -> str
    root_dir = pex_root or ENV.PEX_ROOT
    downloads_dir = _DOWNLOADS_DIRS.get(root_dir)
    if downloads_dir is None:
        downloads_dir = os.path.join(root_dir, "downloads")
        safe_mkdir(downloads_dir)
        _DOWNLOADS_DIRS[root_dir] = downloads_dir
    return downloads_dir


def _strip_indexes_and_repos(package_index_configuration):
    # type: (PackageIndexConfiguration) -> PackageIndexConfiguration
    return PackageIndexConfiguration.create(
        resolver_version=package_index_configuration.resolver_version,
        indexes=[],
        find_links=None,
        network_configuration=package_index_configuration.network_configuration,
        password_entries=package_index_configuration.password_entries,
    )


@attr.s(frozen=True)
class ArtifactDownloader(object):
    package_index_configuration = attr.ib(
        default=PackageIndexConfiguration.create(), converter=_strip_indexes_and_repos
    )  # type: PackageIndexConfiguration
    target = attr.ib(default=LocalInterpreter.create())  # type: Target
    _pip = attr.ib(init=False)  # type: Pip

    def __attrs_post_init__(self):
        object.__setattr__(self, "_pip", get_pip(interpreter=self.target.get_interpreter()))

    @staticmethod
    def _fingerprint_and_move(path):
        # type: (str) -> Fingerprint
        digest = Sha256()
        hashing.file_hash(path, digest)
        fingerprint = digest.hexdigest()
        target_dir = os.path.join(get_downloads_dir(), fingerprint)
        with atomic_directory(target_dir, exclusive=True) as atomic_dir:
            if not atomic_dir.is_finalized():
                shutil.move(path, os.path.join(atomic_dir.work_dir, os.path.basename(path)))
        return Fingerprint(algorithm=fingerprint.algorithm, hash=fingerprint)

    @staticmethod
    def _create_file_artifact(
        url,  # type: str
        fingerprint,  # type: Fingerprint
        verified,  # type: bool
    ):
        # type: (...) -> FileArtifact
        fingerprinted_artifact = Artifact.from_url(url, fingerprint, verified=verified)
        if not isinstance(fingerprinted_artifact, FileArtifact):
            raise ValueError(
                "Expected a file artifact, given url {url} which is a {artifact}.".format(
                    url=url, artifact=fingerprinted_artifact
                )
            )
        return fingerprinted_artifact

    def _download(
        self,
        url,  # type: str
        download_dir,  # type: str
    ):
        # type: (...) -> Job

        for password_entry in self.package_index_configuration.password_entries:
            credentialed_url = password_entry.maybe_inject_in_url(url)
            if credentialed_url:
                url = credentialed_url
                break

        return self._pip.spawn_download_distributions(
            download_dir=download_dir,
            requirements=[url],
            transitive=False,
            target=self.target,
            package_index_configuration=self.package_index_configuration,
        )

    def _download_and_fingerprint(self, url):
        # type: (str) -> SpawnedJob[FileArtifact]
        downloads = get_downloads_dir()
        download_dir = safe_mkdtemp(prefix="fingerprint_artifact.", dir=downloads)
        temp_dest = os.path.join(
            download_dir, os.path.basename(urlparse.unquote(urlparse.urlparse(url).path))
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
        try:
            self._download(url=artifact.url, download_dir=dest_dir).wait()
        except Job.Error as e:
            return Error((e.stderr or str(e)).splitlines()[-1])
        hashing.file_hash(os.path.join(dest_dir, artifact.filename), digest)
        return artifact.filename
