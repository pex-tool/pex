# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import json
import os

from pex import hashing
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import DownloadDir
from pex.common import safe_mkdtemp
from pex.fs import atomic_text_file
from pex.hashing import Sha256, Sha256Fingerprint
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import (
    Artifact,
    FileArtifact,
    LocalProjectArtifact,
    UnFingerprintedArtifact,
    UnFingerprintedLocalProjectArtifact,
)
from pex.result import Error, ResultError, try_
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, Generic
from pex.util import CacheHelper
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import List, Optional, TypeVar, Union

    import attr  # vendor:skip

    from pex.hashing import Hasher, HintedDigest

    _A = TypeVar("_A", bound=UnFingerprintedArtifact)
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class DownloadedArtifact(object):
    _METADATA_VERSION = 3

    class LoadError(Exception):
        pass

    @staticmethod
    def metadata_filename(artifact_dir):
        # type: (str) -> str
        return os.path.join(artifact_dir, "metadata.json")

    @classmethod
    def store(
        cls,
        artifact,  # type: _A
        artifact_dir,  # type: str
        filename,  # type: str
        artifact_digests,  # type: ArtifactDigests
    ):
        # type: (...) -> DownloadedArtifact

        # We store v0 metadata so that Pex downgrades work. The v0 metadata mechanism had no
        # remove & retry upgrade (downgrade) mechanism like v1+ does.
        with atomic_text_file(os.path.join(artifact_dir, "sha1")) as fp:
            fp.write(artifact_digests.legacy_internal_hasher.hexdigest())

        # N.B.: Pip already accounts for subdirectory when it creates source zips from VCS
        # requirements; so we elide unless the archive was a directly downloaded file artifact.
        subdirectory = artifact.subdirectory if isinstance(artifact, FileArtifact) else None

        editable = (
            artifact.editable
            if isinstance(artifact, (LocalProjectArtifact, UnFingerprintedLocalProjectArtifact))
            else False
        )

        fingerprint = artifact_digests.fingerprint()

        with atomic_text_file(cls.metadata_filename(artifact_dir)) as fp:
            json.dump(
                dict(
                    algorithm=artifact_digests.algorithm,
                    hexdigest=fingerprint,
                    filename=filename,
                    subdirectory=subdirectory,
                    editable=editable,
                    version=cls._METADATA_VERSION,
                ),
                fp,
            )

        return cls(
            path=os.path.join(artifact_dir, filename),
            fingerprint=fingerprint,
            subdirectory=subdirectory,
            editable=editable,
        )

    @classmethod
    def load(cls, artifact_dir):
        # type: (str) -> DownloadedArtifact
        metadata_filename = cls.metadata_filename(artifact_dir)
        try:
            with open(metadata_filename, "r") as fp:
                try:
                    metadata = json.load(fp)
                except ValueError as e:
                    raise cls.LoadError(
                        "Failed to decode download artifact JSON metadata in {path}: {err}".format(
                            path=metadata_filename, err=e
                        )
                    )
                if not isinstance(metadata, dict) or cls._METADATA_VERSION != metadata.get(
                    "version"
                ):
                    raise cls.LoadError(
                        "Unexpected downloaded artifact metadata object. Expected JSON metadata "
                        "version {version} but found {metadata}".format(
                            version=cls._METADATA_VERSION, metadata=metadata
                        )
                    )
                return DownloadedArtifact(
                    path=os.path.join(artifact_dir, metadata["filename"]),
                    fingerprint=hashing.new_fingerprint(
                        algorithm=str(metadata["algorithm"]), hexdigest=str(metadata["hexdigest"])
                    ),
                    subdirectory=metadata["subdirectory"],
                    editable=metadata["editable"],
                )
        except (OSError, IOError) as e:
            raise cls.LoadError(
                "Failed to read a downloaded artifact metadata file at {path}: {err}".format(
                    path=metadata_filename, err=e
                )
            )

    path = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: hashing.Fingerprint
    subdirectory = attr.ib(default=None)  # type: Optional[str]
    editable = attr.ib(default=False)  # type: bool


@attr.s(frozen=True)
class ArtifactDigests(object):
    _INTERNAL_FP_TYPE = Sha256Fingerprint

    artifact = attr.ib()  # type: UnFingerprintedArtifact
    legacy_internal_hasher = attr.ib(init=False, factory=hashing.Sha1)  # type: Hasher
    internal_hasher = attr.ib(init=False, factory=_INTERNAL_FP_TYPE.new_hasher)  # type: Hasher
    _check = attr.ib(init=False)  # type: Optional[Hasher]
    digest = attr.ib(init=False)  # type: Hasher

    def __attrs_post_init__(self):
        digests = [
            self.legacy_internal_hasher,
            self.internal_hasher,
        ]  # type: List[HintedDigest]

        check = None  # type: Optional[Hasher]
        # The locking process will have pre-calculated some artifact fingerprints ahead of
        # time; these will be marked as verified and can be trusted.
        if not self.artifact.verified and isinstance(self.artifact, Artifact):
            # For the rest (E.G.: PyPI URLs with embedded fingerprints), we distrust and
            # establish our own fingerprint. This will mostly be wasted effort since we
            # share the same hash algorithm as PyPI currently, but it will serve to upgrade
            # the fingerprint on other cheeseshops that use a lower-grade hash algorithm (
            # See: https://peps.python.org/pep-0503/#specification).
            check = hashlib.new(self.artifact.fingerprint.algorithm)  # External
            digests.append(check)

        object.__setattr__(self, "_check", check)
        object.__setattr__(self, "digest", hashing.MultiDigest(digests))

    def check(self, project_name):
        # type: (ProjectName) -> None

        if self._check:
            assert isinstance(
                self.artifact, Artifact
            ), "We assured artifacts that need a check had a fingerprint above."
            actual_hash = self._check.hexdigest()
            if self.artifact.fingerprint.hash != actual_hash:
                raise ResultError(
                    Error(
                        "Expected {algorithm} hash of {expected_hash} when downloading "
                        "{project_name} but hashed to {actual_hash}.".format(
                            algorithm=self.artifact.fingerprint.algorithm,
                            expected_hash=self.artifact.fingerprint.hash,
                            project_name=project_name,
                            actual_hash=actual_hash,
                        )
                    )
                )

    @property
    def algorithm(self):
        # type: () -> str
        return self._INTERNAL_FP_TYPE.algorithm

    def fingerprint(self):
        # type: () -> hashing.Fingerprint
        return hashing.new_fingerprint(self.algorithm, self.internal_hasher.hexdigest())


class DownloadManager(Generic["_A"]):
    def __init__(self, pex_root=ENV):
        # type: (Union[str, Variables]) -> None
        self._pex_root = pex_root

    def store(
        self,
        artifact,  # type: _A
        project_name,  # type: ProjectName
    ):
        # type: (...) -> DownloadedArtifact

        if isinstance(artifact, UnFingerprintedLocalProjectArtifact) and artifact.editable:
            digest = Sha256()  # type: ignore[unreachable]
            CacheHelper.dir_hash(artifact.directory, digest=digest)
            return DownloadedArtifact(
                artifact.directory, fingerprint=digest.hexdigest(), editable=True
            )

        if hasattr(artifact, "fingerprint"):
            fingerprint = getattr(artifact, "fingerprint")
            download_dir = DownloadDir.create(
                file_hash=fingerprint.hash, pex_root=self._pex_root
            )  # type: str
            with atomic_directory(download_dir) as atomic_dir:
                if atomic_dir.is_finalized():
                    TRACER.log(
                        "Using cached artifact at {} for {}".format(
                            download_dir, artifact.url.raw_url
                        )
                    )
                else:
                    downloaded_artifact = self._download(
                        artifact, project_name, atomic_dir.work_dir
                    )
                    return attr.evolve(
                        downloaded_artifact,
                        path=os.path.join(download_dir, os.path.basename(downloaded_artifact.path)),
                    )
        else:
            download_dir = safe_mkdtemp()
            return self._download(artifact, project_name, download_dir)

        # N.B.: DownloadDir atomic_directory cache hit case.
        try:
            return DownloadedArtifact.load(download_dir)
        except DownloadedArtifact.LoadError as e:
            TRACER.log(
                "Found outdated downloaded artifact metadata, upgrading: {err}".format(err=e)
            )
            artifact_digests = ArtifactDigests(artifact)
            filename = self.digest(
                artifact=artifact,
                project_name=project_name,
                download_dir=download_dir,
                digest=artifact_digests.digest,
            )
            artifact_digests.check(project_name)
            return DownloadedArtifact.store(
                artifact=artifact,
                artifact_dir=download_dir,
                filename=filename,
                artifact_digests=artifact_digests,
            )

    def _download(
        self,
        artifact,  # type: _A
        project_name,  # type: ProjectName
        dest_dir,  # type: str
    ):
        # type: (...) -> DownloadedArtifact

        artifact_digests = ArtifactDigests(artifact)
        with TRACER.timed(
            "Downloading {project_name} from {url}".format(
                project_name=project_name, url=artifact.url.download_url
            )
        ):
            filename = try_(
                self.save(
                    artifact=artifact,
                    project_name=project_name,
                    dest_dir=dest_dir,
                    digest=artifact_digests.digest,
                )
            )
        artifact_digests.check(project_name=project_name)
        return DownloadedArtifact.store(
            artifact=artifact,
            artifact_dir=dest_dir,
            filename=filename,
            artifact_digests=artifact_digests,
        )

    def digest(
        self,
        artifact,  # type: _A
        project_name,  # type: ProjectName
        download_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> str
        """Digest the given `artifact` under `dest_dir` and return the saved file name."""
        raise NotImplementedError()

    def save(
        self,
        artifact,  # type: _A
        project_name,  # type: ProjectName
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]
        """Save and digest the given `artifact` under `dest_dir` and return the saved file name."""
        raise NotImplementedError()
