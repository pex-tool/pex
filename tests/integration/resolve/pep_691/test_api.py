# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

import pytest

from pex.pep_503 import ProjectName
from pex.resolve.pep_691.api import Client
from pex.resolve.pep_691.model import Endpoint, Project
from pex.resolve.resolved_requirement import Fingerprint
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Type


def request(
    url,  # type: str
    content_type,  # type: str
):
    # type: (...) -> Project
    return Client().request(Endpoint(url=url, content_type=content_type))


def assert_error(
    url,  # type: str
    content_type,  # type: str
    expected_exception_type,  # type: Type[Exception]
    prefix,  # type: str
):
    # type: (...) -> None

    with pytest.raises(expected_exception_type, match="^{}.*".format(re.escape(prefix))):
        request(url, content_type)


def test_invalid_content_type():
    # type: () -> None

    assert_error(
        url="https://example.org",
        content_type="text/html",
        expected_exception_type=ValueError,
        prefix=(
            "Asked to request project metadata from https://example.org for text/html but only the "
            "following API content types are accepted:"
        ),
    )


def test_invalid_json():
    # type: () -> None

    assert_error(
        url="https://example.org",
        content_type="application/vnd.pypi.simple.v1+json",
        expected_exception_type=Client.Error,
        prefix=(
            "PEP-691 API request to https://example.org for application/vnd.pypi.simple.v1+json "
            "returned invalid JSON: "
        ),
    )


def test_http_error():
    # type: () -> None

    assert_error(
        url="https://pypi.org/simple/p527-DNE",
        content_type="application/vnd.pypi.simple.v1+json",
        expected_exception_type=Client.Error,
        prefix=(
            "PEP-691 API request to https://pypi.org/simple/p527-DNE for "
            "application/vnd.pypi.simple.v1+json failed: HTTP Error 404: Not Found"
        ),
    )


@pytest.mark.parametrize(
    "content_type", [pytest.param(content_type, id=content_type) for content_type in Client.ACCEPT]
)
def test_valid(content_type):
    # type: (str) -> None

    p537 = request(url="https://pypi.org/simple/p537", content_type=content_type)
    assert ProjectName("p537") == p537.name

    files_by_filename = {file.filename: file for file in p537.files}
    assert (
        Fingerprint(
            algorithm="sha256",
            hash="c1300324000522387b1f0c474db53b081308f78868030e53a2df6f162d3feb86",
        )
        == files_by_filename["p537-1.0.0-cp36-cp36m-macosx_10_13_x86_64.whl"].select_fingerprint()
    )
