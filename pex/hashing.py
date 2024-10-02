# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os

from pex.common import open_zip
from pex.typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from typing import IO, Callable, Iterable, Iterator, Optional, Protocol, Text, Type, TypeVar

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


def dir_hash(
    directory,  # type: Text
    digest,  # type: HintedDigest
    dir_filter=lambda d: True,  # type: Callable[[Text], bool]
    file_filter=lambda f: True,  # type: Callable[[Text], bool]
):
    # type: (...) -> None
    """Digest the contents of a directory in a reproducible manner."""

    top = os.path.realpath(directory)

    def iter_files():
        # type: () -> Iterator[Text]
        for root, dirs, files in os.walk(top, followlinks=True):
            dirs[:] = [d for d in dirs if dir_filter(os.path.join(root, d))]
            for f in files:
                path = os.path.join(root, f)
                if file_filter(path):
                    yield path

    file_paths = sorted(iter_files())

    # Regularize to / as the directory separator so that a dir hash on Unix matches a dir hash on
    # Windows matches a zip hash (see below) of that same dir.
    hashed_names = [os.path.relpath(n, top).replace(os.sep, "/") for n in file_paths]
    digest.update("".join(hashed_names).encode("utf-8"))

    for file_path in file_paths:
        file_hash(file_path, digest)


def zip_hash(
    zip_path,  # type: Text
    digest,  # type: HintedDigest
    relpath=None,  # type: Optional[Text]
    dir_filter=lambda d: True,  # type: Callable[[Text], bool]
    file_filter=lambda f: True,  # type: Callable[[Text], bool]
):
    # type: (...) -> None
    """Digest the contents of a zip file in a reproducible manner.

    If a `relpath` is specified, descend into that path only and take the hash with names recoded
    in the hash relative to the `relpath`.
    """
    with open_zip(zip_path) as zf:
        namelist = (
            [name for name in zf.namelist() if name.startswith(relpath)]
            if relpath
            else zf.namelist()
        )

        dirs = frozenset(name.rstrip("/") for name in namelist if name.endswith("/"))
        accept_dirs = frozenset(d for d in dirs if dir_filter(os.path.basename(d)))
        reject_dirs = dirs - accept_dirs

        accept_files = sorted(
            name
            for name in namelist
            if not name.endswith("/")
            and not any(name.startswith(reject_dir) for reject_dir in reject_dirs)
            and file_filter(os.path.basename(name))
        )

        hashed_names = (
            [os.path.relpath(name, relpath) for name in accept_files] if relpath else accept_files
        )
        digest.update("".join(hashed_names).encode("utf-8"))

        for filename in accept_files:
            update_hash(zf.open(filename, "r"), digest)
