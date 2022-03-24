# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib

import pytest

from pex.hashing import (
    HashlibHasher,
    MultiDigest,
    Sha1Fingerprint,
    Sha256Fingerprint,
    new_fingerprint,
)


def test_fingerprint_equality():
    # type: () -> None

    assert Sha1Fingerprint("foo") == Sha1Fingerprint("foo")
    assert Sha1Fingerprint("foo") != Sha1Fingerprint("bar")

    assert "foo" == Sha1Fingerprint("foo"), (
        "Expected a digest str object to see itself as equal to a Sha256Fingerprint "
        "object with the same digest value"
    )
    assert Sha1Fingerprint("foo") != Sha256Fingerprint(
        "foo"
    ), "Expected fingerprint objects to require types (algorithms) match exactly"


def test_fingerprint_new_hasher():
    # type: () -> None

    assert hashlib.sha1().hexdigest() == Sha1Fingerprint.new_hasher().hexdigest()
    assert hashlib.sha256().hexdigest() == Sha256Fingerprint.new_hasher().hexdigest()


def test_new_fingerprint():
    # type: () -> None

    assert Sha1Fingerprint("foo") == new_fingerprint(algorithm="sha1", hexdigest="foo")
    assert Sha256Fingerprint("foo") == new_fingerprint(algorithm="sha256", hexdigest="foo")

    with pytest.raises(
        ValueError,
        match=(
            r"There is no fingerprint type registered for hash algorithm md5. The supported "
            r"algorithms are: "
        ),
    ):
        new_fingerprint(algorithm="md5", hexdigest="foo")


def test_hasher():
    # type: () -> None

    hasher = Sha1Fingerprint.new_hasher()
    assert isinstance(hasher, HashlibHasher)

    sha1 = hashlib.sha1()
    assert sha1.name == hasher.name
    assert sha1.block_size == hasher.block_size

    multi_digest = MultiDigest((sha1, hasher))
    multi_digest.update(b"foo")
    assert sha1.digest() == hasher.digest()

    fingerprint = hasher.hexdigest()
    assert isinstance(fingerprint, Sha1Fingerprint)
    assert fingerprint == Sha1Fingerprint(sha1.hexdigest())
