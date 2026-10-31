# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import hashlib
import os
from contextlib import contextmanager

from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import IO, Iterable, Iterator, Optional, Text, Type, TypeVar

    from pex.hashing_types import HintedDigest


class Fingerprint(str):
    class Algorithm(object):
        def __get__(
            self,
            _instance,  # type: Optional[Fingerprint]
            owner,  # type: Type[Fingerprint]
        ):
            # type: (...) -> str

            alg = getattr(owner, "_alg", None)
            if alg is None:
                alg = owner.__name__[: -len(Fingerprint.__name__)].lower()
                setattr(owner, "_alg", alg)
            return alg

    algorithm = Algorithm()

    @classmethod
    def new_hasher(cls, data=b""):
        # type: (bytes) -> HashlibHasher
        return HashlibHasher(cls, data=data)

    def __eq__(self, other):
        if isinstance(other, Fingerprint) and type(self) != type(other):
            return False
        return super(Fingerprint, self).__eq__(other)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        # type: () -> int
        return hash((self.algorithm, str(self)))


def new_fingerprint(
    algorithm,  # type: str
    hexdigest,  # type: str
):
    # type: (...) -> Fingerprint

    for subclass in Fingerprint.__subclasses__():
        if subclass.algorithm == algorithm:
            return subclass(hexdigest)

    raise ValueError(
        "There is no fingerprint type registered for hash algorithm {algorithm}. The supported "
        "algorithms are: {algorithms}".format(
            algorithm=algorithm,
            algorithms=", ".join(fp.algorithm for fp in Fingerprint.__subclasses__()),
        )
    )


class Sha1Fingerprint(Fingerprint):
    pass


class Sha256Fingerprint(Fingerprint):
    pass


if TYPE_CHECKING:
    _F = TypeVar("_F", bound=Fingerprint)


class HashlibHasher(Generic["_F"]):
    def __init__(
        self,
        hexdigest_type,  # type: Type[_F]
        data=b"",  # type: bytes
    ):
        # type: (...) -> None
        self._hexdigest_type = hexdigest_type
        self._hasher = hashlib.new(hexdigest_type.algorithm, data)

    @property
    def name(self):
        # type: () -> str
        return self._hasher.name

    @property
    def block_size(self):
        # type: () -> int
        return self._hasher.block_size

    def update(self, data):
        # type: (bytes) -> None
        self._hasher.update(data)

    def digest(self):
        # type: () -> bytes
        return self._hasher.digest()

    def hexdigest(self):
        # type: () -> _F
        return self._hexdigest_type(self._hasher.hexdigest())


class Sha1(HashlibHasher[Sha1Fingerprint]):
    def __init__(self, data=b""):
        # type: (bytes) -> None
        super(Sha1, self).__init__(hexdigest_type=Sha1Fingerprint, data=data)


class Sha256(HashlibHasher[Sha256Fingerprint]):
    def __init__(self, data=b""):
        # type: (bytes) -> None
        super(Sha256, self).__init__(hexdigest_type=Sha256Fingerprint, data=data)


class MultiDigest(object):
    def __init__(self, digests):
        # type: (Iterable[HintedDigest]) -> None
        self._digests = digests
        self._block_size = max(digest.block_size for digest in digests)

    @property
    def block_size(self):
        # type: () -> int
        return self._block_size

    def update(self, data):
        # type: (bytes) -> None
        for digest in self._digests:
            digest.update(data)


def update_hash(
    filelike,  # type: IO[bytes]
    digest,  # type: HintedDigest
):
    # type: (...) -> None
    """Update the digest of a single file in a memory-efficient manner."""
    block_size = digest.block_size * 1024
    for chunk in iter(lambda: filelike.read(block_size), b""):
        digest.update(chunk)


def file_hash(
    path,  # type: Text
    digest,  # type: HintedDigest
):
    # type: (...) -> None
    """Digest of a single file in a memory-efficient manner."""
    with open(path, "rb") as fp:
        update_hash(filelike=fp, digest=digest)


@contextmanager
def lock_pex_project_dir():
    # type: () -> Iterator[None]

    if "_PEX_LOCKED_PROJECT_DIR" in os.environ:
        # N.B.: We're in a subprocess of a root Pex invocation that holds the lock; so it's
        # ok to proceed.
        yield
        return

    from pex.fs import lock

    lck = lock.acquire(__file__ + ".lck", exclusive=True)
    os.environ["_PEX_LOCKED_PROJECT_DIR"] = str(os.getpid())
    try:
        yield
    finally:
        lck.release()
        del os.environ["_PEX_LOCKED_PROJECT_DIR"]


@contextmanager
def locked_directory(directory):
    # type: (Text) -> Iterator[Text]

    top = os.path.realpath(directory)
    if __file__:
        maybe_pex_project_directory = os.path.dirname(os.path.dirname(__file__))
        if directory == maybe_pex_project_directory and os.path.isfile(
            os.path.join(maybe_pex_project_directory, "pyproject.toml")
        ):
            with lock_pex_project_dir():
                yield top
            return

    yield top
