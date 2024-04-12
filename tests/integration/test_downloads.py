# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import hashlib
import os.path

import pytest

from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.downloads import ArtifactDownloader
from pex.resolve.locked_resolve import Artifact, FileArtifact, LockConfiguration, LockStyle
from pex.resolve.resolved_requirement import Fingerprint, PartialArtifact
from pex.typing import TYPE_CHECKING
from testing import IS_LINUX

if TYPE_CHECKING:
    pass


def file_artifact(
    url,  # type: str
    sha256,  # type: str
):
    # type: (...) -> FileArtifact
    artifact = Artifact.from_url(
        url=url, fingerprint=Fingerprint(algorithm="sha256", hash=sha256), verified=True
    )
    assert isinstance(artifact, FileArtifact)
    return artifact


LINUX_ARTIFACT = file_artifact(
    url=(
        "https://files.pythonhosted.org/packages/6d/c6/"
        "6a4e46802e8690d50ba6a56c7f79ac283e703fcfa0fdae8e41909c8cef1f/"
        "psutil-5.9.1-cp310-cp310-"
        "manylinux_2_12_x86_64"
        ".manylinux2010_x86_64"
        ".manylinux_2_17_x86_64"
        ".manylinux2014_x86_64.whl"
    ),
    sha256="29a442e25fab1f4d05e2655bb1b8ab6887981838d22effa2396d584b740194de",
)

MAC_ARTIFACT = file_artifact(
    url=(
        "https://files.pythonhosted.org/packages/d1/16/"
        "6239e76ab5d990dc7866bc22a80585f73421588d63b42884d607f5f815e2/"
        "psutil-5.9.1-cp310-cp310-macosx_10_9_x86_64.whl"
    ),
    sha256="c7be9d7f5b0d206f0bbc3794b8e16fb7dbc53ec9e40bbe8787c6f2d38efcf6c9",
)


@pytest.fixture
def downloader():
    # type: () -> ArtifactDownloader
    return ArtifactDownloader(
        resolver=ConfiguredResolver.default(),
        lock_configuration=LockConfiguration(style=LockStyle.UNIVERSAL),
    )


def test_issue_1849_download_foreign_artifact(
    tmpdir,  # type: str
    downloader,  # type: ArtifactDownloader
):
    # type: (...) -> None

    foreign_artifact = MAC_ARTIFACT if IS_LINUX else LINUX_ARTIFACT

    dest_dir = os.path.join(str(tmpdir), "dest_dir")
    assert foreign_artifact.filename == downloader.download(
        foreign_artifact, dest_dir=dest_dir, digest=hashlib.sha256()
    )


def test_issue_1849_fingerprint_foreign_artifact(
    tmpdir,  # type: str
    downloader,  # type: ArtifactDownloader
):
    # type: (...) -> None

    expected_artifacts = [LINUX_ARTIFACT, MAC_ARTIFACT]
    assert expected_artifacts == list(
        downloader.fingerprint([PartialArtifact(artifact.url) for artifact in expected_artifacts])
    )
