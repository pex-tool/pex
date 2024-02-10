# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import re
from io import BytesIO

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]

import pytest

from pex.fetcher import URLFetcher
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.pep_691.api import Client
from pex.resolve.pep_691.model import Endpoint, File, Meta, Project
from pex.resolve.resolved_requirement import ArtifactURL, Fingerprint
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict


def client_request(response_body):
    # type: (bytes) -> Project
    with mock.patch.object(URLFetcher, "get_body_stream", return_value=BytesIO(response_body)):
        return Client().request(
            Endpoint(
                url="https://example.org/simple/",
                content_type="application/vnd.pypi.simple.v1+json",
            )
        )


def test_request_nominal():
    # type: () -> None
    assert Project(
        name=ProjectName("p537"),
        files=SortedTuple(
            [
                File(
                    filename="file.tar.gz",
                    url=ArtifactURL.parse("https://files.example.org/simple/file.tar.gz"),
                    hashes=SortedTuple(
                        [
                            Fingerprint("md5", "weak"),
                            Fingerprint("sha256", "strong"),
                        ]
                    ),
                ),
            ]
        ),
        meta=Meta(api_version=Version("1.2")),
    ) == client_request(
        json.dumps(
            {
                "name": "p537",
                "files": [
                    {
                        "filename": "file.tar.gz",
                        "url": "https://files.example.org/simple/file.tar.gz",
                        "hashes": {"md5": "weak", "sha256": "strong"},
                    },
                ],
                "meta": {"api-version": "1.2"},
            }
        ).encode("utf-8")
    )


def test_request_url_absolutize():
    # type: () -> None
    assert Project(
        name=ProjectName("p537"),
        files=SortedTuple(
            [
                File(
                    filename="file.whl",
                    url=ArtifactURL.parse("https://example.org/simple/__files/relative/file.whl"),
                    hashes=SortedTuple([Fingerprint("md5", "collision")]),
                ),
            ]
        ),
        meta=Meta(api_version=Version("1.2")),
    ) == client_request(
        json.dumps(
            {
                "name": "p537",
                "files": [
                    {
                        "filename": "file.whl",
                        "url": "__files/relative/file.whl",
                        "hashes": {"md5": "collision"},
                    },
                ],
                "meta": {"api-version": "1.2"},
            }
        ).encode("utf-8")
    )


def test_bad_json_response():
    # type: () -> None
    with pytest.raises(
        Client.Error,
        match=r"^{}.*".format(
            re.escape(
                "PEP-691 API request to https://example.org/simple/ for "
                "application/vnd.pypi.simple.v1+json returned invalid JSON: "
            )
        ),
    ):
        client_request(b"[[]")


def serialize_response(data):
    # type: (Dict[str, Any]) -> bytes
    return json.dumps(data, indent=2).encode("utf-8")


def assert_response_error_starts_with(
    response,  # type: Dict[str, Any]
    prefix,  # type: str
):
    # type: (...) -> None

    with pytest.raises(Client.Error, match=r"^{}.*".format(re.escape(prefix))):
        client_request(serialize_response(response))


def test_unsupported_api_version():
    assert_response_error_starts_with(
        {"name": "p537", "files": [], "meta": {"api-version": "2.0"}},
        prefix=(
            "PEP-691 API response from https://example.org/simple/ for "
            "application/vnd.pypi.simple.v1+json reports an api-version of 2.0 and Pex "
            "currently only supports api-version 1.x:"
        ),
    )


@pytest.fixture
def valid_response():
    # type: () -> Dict[str, Any]
    return {
        "name": "p537",
        "files": [
            {
                "filename": "file.whl",
                "url": "__files/relative/file.whl",
                "hashes": {"md5": "collision"},
            }
        ],
        "meta": {"api-version": "1.2"},
    }


def test_missing_name(valid_response):
    # type: (Dict[str, Any]) -> None

    valid_response.pop("name")
    assert_response_error_starts_with(
        valid_response,
        prefix=(
            "PEP-691 API response from https://example.org/simple/ for "
            "application/vnd.pypi.simple.v1+json did not contain the expected key '.[\"name\"]':"
        ),
    )


def test_missing_meta_version(valid_response):
    # type: (Dict[str, Any]) -> None

    valid_response["meta"].pop("api-version")
    assert_response_error_starts_with(
        valid_response,
        prefix=(
            "PEP-691 API response from https://example.org/simple/ for "
            "application/vnd.pypi.simple.v1+json did not contain the expected key "
            "'.meta[\"api-version\"]':"
        ),
    )


def test_bad_hash(valid_response):
    # type: (Dict[str, Any]) -> None

    valid_response["files"][0]["hashes"]["sha256"] = 42
    assert_response_error_starts_with(
        valid_response,
        prefix=(
            "PEP-691 API response from https://example.org/simple/ for "
            "application/vnd.pypi.simple.v1+json reports a hash value of 42 of type int for "
            "'.files[0].hashes[\"sha256\"]' but hash values should be strings:"
        ),
    )
