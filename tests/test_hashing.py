# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import os.path

import pytest

from pex.common import is_pyc_file, open_zip
from pex.hashing import (
    HashlibHasher,
    MultiDigest,
    Sha1Fingerprint,
    Sha256,
    Sha256Fingerprint,
    dir_hash,
    new_fingerprint,
    zip_hash,
)
from testing.pytest_utils.tmp import Tempdir


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


def test_zip_hash_consistent_with_dir_hash(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type str
):
    # type: (...) -> None

    zip_file = os.path.join(
        pex_project_dir, "tests", "example_packages", "aws_cfn_bootstrap-1.4-py2-none-any.whl"
    )

    dir_filter = lambda dir_path: os.path.basename(dir_path) != "resources"
    file_filter = lambda f: not is_pyc_file(f)

    zip_digest = Sha256()
    zip_hash(zip_path=zip_file, digest=zip_digest, dir_filter=dir_filter, file_filter=file_filter)

    relpath_zip_digest = Sha256()
    zip_hash(
        zip_path=zip_file,
        digest=relpath_zip_digest,
        relpath="cfnbootstrap",
        dir_filter=dir_filter,
        file_filter=file_filter,
    )

    unzipped_dir = tmpdir.join("unzipped")
    with open_zip(zip_file) as zf:
        zf.extractall(unzipped_dir)

    dir_digest = Sha256()
    dir_hash(
        directory=unzipped_dir, digest=dir_digest, dir_filter=dir_filter, file_filter=file_filter
    )

    relpath_dir_digest = Sha256()
    dir_hash(
        directory=os.path.join(unzipped_dir, "cfnbootstrap"),
        digest=relpath_dir_digest,
        dir_filter=dir_filter,
        file_filter=file_filter,
    )

    assert dir_digest.hexdigest() == zip_digest.hexdigest()
    assert dir_digest.hexdigest() != relpath_dir_digest.hexdigest()
    assert relpath_dir_digest.hexdigest() == relpath_zip_digest.hexdigest()
