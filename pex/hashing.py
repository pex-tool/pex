# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os

from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import IO, Callable, Iterable, Iterator, Optional, Protocol, Type, TypeVar

    class HintedDigest(Protocol):
        @property
        def block_size(self):
            # type: () -> int
            pass

        def update(self, data):
            # type: (bytes) -> None
            pass

    class Hasher(HintedDigest, Protocol):
        @property
        def name(self):
            # type: () -> str
            pass

        def digest(self):
            # type: () -> bytes
            pass

        def hexdigest(self):
            # type: () -> str
            pass


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
    path,  # type: str
    digest,  # type: HintedDigest
):
    # type: (...) -> None
    """Digest of a single file in a memory-efficient manner."""
    with open(path, "rb") as fp:
        update_hash(filelike=fp, digest=digest)


def dir_hash(
    directory,  # type: str
    digest,  # type: HintedDigest
    dir_filter=lambda dirs: dirs,  # type: Callable[[Iterable[str]], Iterable[str]]
    file_filter=lambda files: files,  # type: Callable[[Iterable[str]], Iterable[str]]
):
    # type: (...) -> None
    """Digest the contents of a directory in a reproducible manner."""

    def iter_files():
        # type: () -> Iterator[str]
        normpath = os.path.realpath(os.path.normpath(directory))
        for root, dirs, files in os.walk(normpath):
            dirs[:] = list(dir_filter(dirs))
            for f in file_filter(files):
                yield os.path.relpath(os.path.join(root, f), normpath)

    names = sorted(iter_files())

    # Always use / as the path separator, since that's what zip uses.
    hashed_names = [n.replace(os.sep, "/") for n in names]
    digest.update("".join(hashed_names).encode("utf-8"))

    for name in names:
        file_hash(os.path.join(directory, name), digest)
