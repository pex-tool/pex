# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import json
import os

from pex import hashing
from pex.common import FileLockStyle, atomic_directory, safe_rmtree
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import Artifact
from pex.result import Error, ResultError, try_
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, Generic
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import List, Optional, TypeVar, Union

    import attr  # vendor:skip

    from pex.hashing import HintedDigest

    _A = TypeVar("_A", bound=Artifact)
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class DownloadedArtifact(object):
    _METADATA_VERSION = 1

    class LoadError(Exception):
        pass

    @staticmethod
    def metadata_filename(artifact_dir):
        # type: (str) -> str
        return os.path.join(artifact_dir, "metadata.json")

    @classmethod
    def store(
        cls,
        artifact_dir,  # type str
        filename,  # type: str
        legacy_fingerprint,  # type: hashing.Sha1Fingerprint
        fingerprint,  # type: hashing.Fingerprint
    ):
        # type: (...) -> None

        # We store v0 metadata so that Pex downgrades work. The v0 metadata mechanism had no
        # remove & retry upgrade (downgrade) mechanism like v1+ does.
        with open(os.path.join(artifact_dir, "sha1"), "w") as fp:
            fp.write(legacy_fingerprint)

        with open(cls.metadata_filename(artifact_dir), "w") as fp:
            json.dump(
                dict(
                    algorithm=fingerprint.algorithm,
                    hexdigest=fingerprint,
                    filename=filename,
                    version=cls._METADATA_VERSION,
                ),
                fp,
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
                )
        except (OSError, IOError) as e:
            raise cls.LoadError(
                "Failed to read a downloaded artifact metadata file at {path}: {err}".format(
                    path=metadata_filename, err=e
                )
            )

    path = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: hashing.Fingerprint


class DownloadManager(Generic["_A"]):
    def __init__(
        self,
        pex_root=None,  # type: Optional[str]
        file_lock_style=FileLockStyle.POSIX,  # type: FileLockStyle.Value
    ):
        # type: (...) -> None
        self._download_dir = os.path.join(pex_root or ENV.PEX_ROOT, "downloads")
        self._file_lock_style = file_lock_style

    def store(
        self,
        artifact,  # type: _A
        project_name,  # type: ProjectName
        retry=True,  # type: bool
    ):
        # type: (...) -> DownloadedArtifact

        download_dir = os.path.join(self._download_dir, artifact.fingerprint.hash)
        with atomic_directory(download_dir, exclusive=self._file_lock_style) as atomic_dir:
            if atomic_dir.is_finalized():
                TRACER.log("Using cached artifact at {} for {}".format(download_dir, artifact))
            else:
                legacy_internal_fingerprint = hashing.Sha1()  # Legacy internal
                internal_fingerprint = hashing.Sha256()  # Internal
                digests = [
                    legacy_internal_fingerprint,
                    internal_fingerprint,
                ]  # type: List[HintedDigest]

                # The locking process will have pre-calculated some artifact fingerprints ahead of
                # time; these will be marked as verified and can be trusted.
                if not artifact.verified:
                    # For the rest (E.G.: PyPI URLs with embedded fingerprints), we distrust and
                    # establish our own fingerprint. This will mostly be wasted effort since we
                    # share the same hash algorithm as PyPI currently, but it will serve to upgrade
                    # the fingerprint on other cheeseshops that use a lower-grade hash algorithm (
                    # See: https://peps.python.org/pep-0503/#specification).
                    check = hashlib.new(artifact.fingerprint.algorithm)  # External
                    digests.append(check)

                with TRACER.timed("Downloading {artifact}".format(artifact=artifact)):
                    filename = try_(
                        self.save(
                            artifact=artifact,
                            project_name=project_name,
                            dest_dir=atomic_dir.work_dir,
                            digest=hashing.MultiDigest(digests),
                        )
                    )

                if not artifact.verified:
                    actual_hash = check.hexdigest()
                    if artifact.fingerprint.hash != actual_hash:
                        raise ResultError(
                            Error(
                                "Expected {algorithm} hash of {expected_hash} when downloading "
                                "{project_name} but hashed to {actual_hash}.".format(
                                    algorithm=artifact.fingerprint.algorithm,
                                    expected_hash=artifact.fingerprint.hash,
                                    project_name=project_name,
                                    actual_hash=actual_hash,
                                )
                            )
                        )

                DownloadedArtifact.store(
                    artifact_dir=atomic_dir.work_dir,
                    filename=filename,
                    legacy_fingerprint=legacy_internal_fingerprint.hexdigest(),
                    fingerprint=internal_fingerprint.hexdigest(),
                )
        try:
            return DownloadedArtifact.load(download_dir)
        except DownloadedArtifact.LoadError as e:
            if not retry:
                raise ResultError(Error(str(e)))

            TRACER.log(
                "Found outdated downloaded artifact metadata, upgrading: {err}".format(err=e)
            )
            safe_rmtree(download_dir)
            return self.store(artifact, project_name, retry=False)

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
