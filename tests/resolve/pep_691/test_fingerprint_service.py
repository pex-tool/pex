# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import shutil

import pytest

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]

from pex.compatibility import urlparse
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.pep_691.api import Client
from pex.resolve.pep_691.fingerprint_service import FingerprintService
from pex.resolve.pep_691.model import Endpoint, File, Meta, Project
from pex.resolve.resolved_requirement import ArtifactURL, Fingerprint, PartialArtifact
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


ENDPOINT = Endpoint("https://example.org/simple/foo", "x/y")


@pytest.fixture
def db_dir(tmpdir):
    # type: (Any) -> str
    return os.path.join(str(tmpdir), "pep_691")


def file(
    url,  # type: str
    **hashes  # type: str
):
    # type: (...) -> File
    return File(
        filename=os.path.basename(urlparse.urlparse(url).path),
        url=ArtifactURL.parse(url),
        hashes=SortedTuple(
            Fingerprint(algorithm=algorithm, hash=hash_) for algorithm, hash_ in hashes.items()
        ),
    )


def create_project(
    name,  # type: str
    *files  # type: File
):
    # type: (...) -> Project
    return Project(
        name=ProjectName(name), files=SortedTuple(files), meta=Meta(api_version=Version("1.0"))
    )


def test_no_fingerprints(db_dir):
    # type: (str) -> None

    with mock.patch.object(Client, "request", return_value=create_project("foo")) as request:
        fingerprint_service = FingerprintService(db_dir=db_dir)
        artifacts = list(
            fingerprint_service.fingerprint(
                endpoints={ENDPOINT},
                artifacts=[PartialArtifact(url="https://files.example.org/foo")],
            )
        )
        assert [PartialArtifact(url="https://files.example.org/foo")] == artifacts
    request.assert_called_once_with(ENDPOINT)


def test_no_matching_fingerprints(db_dir):
    # type: (str) -> None

    with mock.patch.object(
        Client,
        "request",
        return_value=create_project(
            "foo",
            file("https://files.example.org/foo-1.0.tar.gz", md5="weak"),
            file("https://files.example.org/foo-2.0.tar.gz", sha256="strong"),
        ),
    ) as request:
        fingerprint_service = FingerprintService(db_dir=db_dir)
        artifacts = list(
            fingerprint_service.fingerprint(
                endpoints={ENDPOINT},
                artifacts=[PartialArtifact(url="https://files.example.org/foo-1.1.tar.gz")],
            )
        )
        assert [PartialArtifact(url="https://files.example.org/foo-1.1.tar.gz")] == artifacts
    request.assert_called_once_with(ENDPOINT)


def test_cache_miss_retries(db_dir):
    # type: (Any) -> None

    endpoint = Endpoint("https://example.org/simple/foo", "x/y")
    attempts = 3

    with mock.patch.object(
        Client,
        "request",
        return_value=create_project(
            "foo",
            file("https://files.example.org/foo-1.0.tar.gz", md5="weak"),
            file("https://files.example.org/foo-2.0.tar.gz", sha256="strong"),
        ),
    ) as request:
        fingerprint_service = FingerprintService(db_dir=db_dir)
        for _ in range(attempts):

            artifacts = list(
                fingerprint_service.fingerprint(
                    endpoints={endpoint},
                    artifacts=[PartialArtifact(url="https://files.example.org/foo-1.1.tar.gz")],
                )
            )
            assert [PartialArtifact(url="https://files.example.org/foo-1.1.tar.gz")] == artifacts

    # We shouldn't cache misses.
    request.assert_has_calls([mock.call(endpoint) for _ in range(attempts)])


def test_cache_hit(tmpdir):
    # type: (Any) -> None

    db_dir = os.path.join(str(tmpdir), "pep_691")
    endpoint = Endpoint("https://example.org/simple/foo", "x/y")
    initial_artifact = PartialArtifact(url="https://files.example.org/foo-1.1.tar.gz")
    expected_artifact = PartialArtifact(
        url="https://files.example.org/foo-1.1.tar.gz",
        fingerprint=Fingerprint(algorithm="md5", hash="weak"),
    )

    with mock.patch.object(
        Client,
        "request",
        return_value=create_project(
            "foo", file("https://files.example.org/foo-1.1.tar.gz", md5="weak")
        ),
    ) as request:
        fingerprint_service = FingerprintService(db_dir=db_dir)
        for _ in range(3):
            artifacts = list(
                fingerprint_service.fingerprint(endpoints={endpoint}, artifacts=[initial_artifact])
            )
            assert [expected_artifact] == artifacts

        # We should cache the hit and not need to call the API again.
        request.assert_called_once_with(endpoint)

        # Unless the cache is wiped out.
        shutil.rmtree(db_dir)
        request.reset_mock()
        assert [expected_artifact] == list(
            fingerprint_service.fingerprint(endpoints={endpoint}, artifacts=[initial_artifact])
        )
        request.assert_called_once_with(endpoint)


def test_mixed(db_dir):
    # type: (str) -> None

    responses = {
        Endpoint("https://example.org/simple/foo", "a/b"): create_project(
            "foo",
            file("https://files.example.org/foo-1.0.tar.gz", md5="weak"),
            file("https://files.example.org/foo-2.0.tar.gz", sha256="strong", sha384="fancy"),
        ),
        Endpoint("https://example.org/simple/bar", "x/y"): create_project(
            "bar", file("https://files.example.org/bar-1.1.tar.gz", sha1="middling", sha384="fancy")
        ),
    }

    with mock.patch.object(Client, "request", side_effect=responses.get) as request:
        fingerprint_service = FingerprintService(db_dir=db_dir)
        artifacts = sorted(
            fingerprint_service.fingerprint(
                endpoints=set(responses),
                artifacts=[
                    PartialArtifact(url="https://files.example.org/foo-1.0.tar.gz"),
                    PartialArtifact(url="https://files.example.org/foo-2.0.tar.gz"),
                    PartialArtifact(url="https://files.example.org/bar-1.1.tar.gz"),
                    PartialArtifact(url="https://files.example.org/baz-2.0.tar.gz"),
                ],
            )
        )
        assert (
            sorted(
                [
                    PartialArtifact(
                        url="https://files.example.org/foo-1.0.tar.gz",
                        fingerprint=Fingerprint("md5", "weak"),
                    ),
                    PartialArtifact(
                        url="https://files.example.org/foo-2.0.tar.gz",
                        fingerprint=Fingerprint("sha256", "strong"),
                    ),
                    PartialArtifact(
                        url="https://files.example.org/bar-1.1.tar.gz",
                        fingerprint=Fingerprint("sha384", "fancy"),
                    ),
                    PartialArtifact(url="https://files.example.org/baz-2.0.tar.gz"),
                ]
            )
            == artifacts
        )
    request.assert_has_calls([mock.call(endpoint) for endpoint in responses], any_order=True)
