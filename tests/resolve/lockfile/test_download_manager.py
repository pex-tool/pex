# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
from io import BytesIO

import pytest

from pex import hashing
from pex.hashing import Sha1Fingerprint, Sha256Fingerprint
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import FileArtifact
from pex.resolve.lockfile.download_manager import DownloadedArtifact, DownloadManager
from pex.resolve.resolved_requirement import Fingerprint
from pex.result import Error, catch
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List, Optional, Union

    import attr  # vendor:skip

    from pex.hashing import HintedDigest
else:
    from pex.third_party import attr


class FakeDownloadManager(DownloadManager[FileArtifact]):
    def __init__(
        self,
        content,  # type: bytes
        pex_root=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        super(FakeDownloadManager, self).__init__(pex_root=pex_root)
        self._content = content
        self._calls = []  # type: List[str]

    @property
    def save_calls(self):
        # type: () -> List[str]
        return self._calls

    def save(
        self,
        artifact,  # type: FileArtifact
        project_name,  # type: ProjectName
        dest_dir,  # type: str
        digest,  # type: HintedDigest
    ):
        # type: (...) -> Union[str, Error]
        self.save_calls.append(dest_dir)
        digest.update(self._content)
        return artifact.filename


@pytest.fixture
def expected_content():
    # type: () -> bytes
    return b"expected content"


@pytest.fixture
def project_name():
    # type: () -> ProjectName
    return ProjectName("foo")


@pytest.fixture
def artifact(expected_content):
    # type: (bytes) -> FileArtifact
    return FileArtifact(
        url="file:///foo-1.0.tar.gz",
        fingerprint=Fingerprint.from_stream(BytesIO(expected_content), algorithm="sha1"),
        filename="foo-1.0.tar.gz",
        verified=False,
    )


@pytest.fixture
def pex_root(tmpdir):
    # type: (Any) -> str
    return os.path.join(str(tmpdir), "pex_root")


@pytest.fixture
def download_manager(
    expected_content,  # type: bytes
    pex_root,  # type: Any
):
    # type: (...) -> FakeDownloadManager
    return FakeDownloadManager(content=expected_content, pex_root=pex_root)


def test_storage_cache(
    artifact,  # type: FileArtifact
    project_name,  # type: ProjectName
    download_manager,  # type: FakeDownloadManager
):
    # type: (...) -> None

    downloaded_artifact1 = download_manager.store(artifact, project_name)
    downloaded_artifact2 = download_manager.store(artifact, project_name)
    assert downloaded_artifact1 == downloaded_artifact2
    assert 1 == len(download_manager.save_calls)


def test_storage_version_upgrade(
    artifact,  # type: FileArtifact
    project_name,  # type: ProjectName
    download_manager,  # type: FakeDownloadManager
):
    # type: (...) -> None

    downloaded_artifact1 = download_manager.store(artifact, project_name)

    # If the storage metadata is not of the expected version, filename or just not present, we
    # expect the artifact to be re-stored afresh.
    files = tuple(
        os.path.join(root, f)
        for root, _, files in os.walk(os.path.dirname(downloaded_artifact1.path))
        for f in files
    )
    assert len(files) > 0, "We expect at least one metadata file."
    for f in files:
        os.unlink(f)

    downloaded_artifact2 = download_manager.store(artifact, project_name)
    assert downloaded_artifact1 == downloaded_artifact2
    assert 2 == len(set(download_manager.save_calls)), (
        "Expected two save calls, each with a different atomic directory work dir signalling a "
        "re-build of the artifact storage"
    )


def test_storage_version_downgrade_v0(tmpdir):
    # type: (Any) -> None

    DownloadedArtifact.store(
        artifact_dir=str(tmpdir),
        filename="foo",
        legacy_fingerprint=Sha1Fingerprint("bar"),
        fingerprint=Sha256Fingerprint("baz"),
    )

    # We should always be emitting v0 metadata since versions of Pex that emitted that format did
    # not have an upgrade (downgrade) mechanism.
    with open(os.path.join(str(tmpdir), "sha1")) as fp:
        assert "bar" == fp.read()

    with open(DownloadedArtifact.metadata_filename(str(tmpdir))) as fp:
        assert dict(algorithm="sha256", hexdigest="baz", filename="foo", version=1) == json.load(fp)


def test_fingerprint_checking(
    expected_content,  # type: bytes
    artifact,  # type: FileArtifact
    project_name,  # type: ProjectName
    pex_root,  # type: str
):
    # type: (...) -> None

    # We expect un-verified artifacts to have their hashes checked against the expected (locked)
    # values.
    actual_content = b"unexpected content"
    download_manager = FakeDownloadManager(content=actual_content, pex_root=pex_root)
    expected_sha1_hash = hashing.Sha1(expected_content).hexdigest()
    assert Error(
        "Expected sha1 hash of {expected_hash} when downloading foo but hashed to "
        "{actual_hash}.".format(
            expected_hash=expected_sha1_hash, actual_hash=hashing.Sha1(actual_content).hexdigest()
        )
    ) == catch(download_manager.store, artifact, project_name)

    # But when the artifact hash is marked verified, no hash checking should occur.
    verified_artifact = attr.evolve(artifact, verified=True)
    expected_artifact_dir = os.path.join(pex_root, "downloads", expected_sha1_hash)
    downloaded_artifact = download_manager.store(verified_artifact, project_name)
    assert (
        DownloadedArtifact(
            path=os.path.join(expected_artifact_dir, "foo-1.0.tar.gz"),
            fingerprint=hashing.Sha256(actual_content).hexdigest(),
        )
        == downloaded_artifact
    )
    assert downloaded_artifact == DownloadedArtifact.load(artifact_dir=expected_artifact_dir)
