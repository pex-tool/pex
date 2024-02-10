# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.requirements import ArchiveScheme
from pex.resolve.resolved_requirement import ArtifactURL, Fingerprint


def test_artifact_url_escaping():
    # type: () -> None

    with_space = ArtifactURL.parse("file:///a/path/with%20space")
    assert "file" == with_space.scheme
    assert "/a/path/with space" == with_space.path
    assert not with_space.is_wheel
    assert "file:///a/path/with%20space" == with_space.raw_url
    assert "file:///a/path/with%20space" == with_space.download_url
    assert "file:///a/path/with space" == with_space.normalized_url
    assert not with_space.fragment_parameters
    assert not with_space.fingerprints
    assert not with_space.fingerprint


def test_artifact_url_with_hash():
    # type: () -> None
    with_hash = ArtifactURL.parse(
        "https://example.com/a/path/with%2Bplus.whl"
        "?query=how"
        "#sha1=abcd1234&foo=bar&sha256=1234abcd&foo=baz"
    )
    assert ArchiveScheme.HTTPS is with_hash.scheme
    assert "/a/path/with+plus.whl" == with_hash.path
    assert with_hash.is_wheel
    assert (
        "https://example.com/a/path/with%2Bplus.whl"
        "?query=how"
        "#sha1=abcd1234&foo=bar&sha256=1234abcd&foo=baz" == with_hash.raw_url
    )
    assert (
        "https://example.com/a/path/with%2Bplus.whl?query=how#foo=bar&foo=baz"
        == with_hash.download_url
    )
    assert "https://example.com/a/path/with+plus.whl" == with_hash.normalized_url
    assert {"foo": ["bar", "baz"]} == {
        name: list(values) for name, values in with_hash.fragment_parameters.items()
    }
    assert (
        Fingerprint("sha256", "1234abcd"),
        Fingerprint("sha1", "abcd1234"),
    ) == with_hash.fingerprints
    assert Fingerprint("sha256", "1234abcd") == with_hash.fingerprint
