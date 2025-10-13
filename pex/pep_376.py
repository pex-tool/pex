# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import base64
import csv
import hashlib
import io
import os
from fileinput import FileInput

from pex import hashing
from pex.common import safe_open
from pex.compatibility import PY2
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO, Callable, Iterable, Iterator, Optional, Protocol, Text, Union

    import attr  # vendor:skip

    from pex.hashing import Hasher

    class CSVWriter(Protocol):
        def writerow(self, row):
            # type: (Iterable[Union[str, int]]) -> None
            pass

else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Digest(object):
    algorithm = attr.ib()  # type: str
    encoded_hash = attr.ib()  # type: str

    def new_hasher(self):
        # type: () -> Hasher
        return hashlib.new(self.algorithm)


@attr.s(frozen=True)
class Hash(object):
    @classmethod
    def create(cls, hasher):
        # type: (Hasher) -> Hash

        # The fingerprint encoding is defined for PEP-376 RECORD files as `urlsafe-base64-nopad`
        # which is fully spelled out in code in PEP-427:
        # + https://peps.python.org/pep-0376/#record
        # + https://peps.python.org/pep-0427/#appendix
        fingerprint = base64.urlsafe_b64encode(hasher.digest()).rstrip(b"=")

        # N.B.: The algorithm is all caps under Python 2.7, but lower case under Python 3; so we
        # normalize.
        alg = hasher.name.lower()

        return cls(value="{alg}={hash}".format(alg=alg, hash=fingerprint.decode("ascii")))

    value = attr.ib()  # type: str

    def __str__(self):
        # type: () -> str
        return self.value


@attr.s(frozen=True)
class InstalledFile(object):
    """The record of a single installed file from a PEP 376 RECORD file.

    See: https://peps.python.org/pep-0376/#record
    """

    path = attr.ib()  # type: Text
    hash = attr.ib(default=None)  # type: Optional[Hash]
    size = attr.ib(default=None)  # type: Optional[int]


def create_installed_file(
    path,  # type: Text
    dest_dir,  # type: str
):
    # type: (...) -> InstalledFile
    hasher = hashlib.sha256()
    hashing.file_hash(path, digest=hasher)
    return InstalledFile(
        path=os.path.relpath(path, dest_dir),
        hash=Hash.create(hasher),
        size=os.stat(path).st_size,
    )


class RecordError(Exception):
    pass


class RecordNotFoundError(RecordError):
    """Indicates a distribution's RECORD metadata could not be found."""


class UnrecognizedInstallationSchemeError(RecordError):
    """Indicates a distribution's RECORD was nested in an unrecognized installation scheme."""


@attr.s(frozen=True)
class DistInfoFile(object):
    path = attr.ib()  # type: Text
    content = attr.ib()  # type: bytes


@attr.s(frozen=True)
class Record(object):
    """Represents the PEP-376 RECORD of an installed wheel.

    See: https://peps.python.org/pep-0376/#record
    """

    @classmethod
    def write_fp(
        cls,
        fp,  # type: IO
        installed_files,  # type: Iterable[InstalledFile]
        eol="\n",  # type: str
    ):
        # type: (...) -> None
        csv_writer = csv.writer(fp, delimiter=",", quotechar='"', lineterminator=eol)
        for installed_file in installed_files:
            csv_writer.writerow(attr.astuple(installed_file, recurse=False))

    @classmethod
    def write_bytes(
        cls,
        installed_files,  # type: Iterable[InstalledFile]
        eol="\n",  # type: str
    ):
        # type: (...) -> bytes
        if PY2:
            record_fp = io.BytesIO()
            cls.write_fp(fp=record_fp, installed_files=installed_files, eol=eol)
            return record_fp.getvalue()
        else:
            record_fp = io.StringIO()
            cls.write_fp(fp=record_fp, installed_files=installed_files, eol=eol)
            return record_fp.getvalue().encode("utf-8")

    @classmethod
    def write(
        cls,
        dst,  # type: Text
        installed_files,  # type: Iterable[InstalledFile]
        eol="\n",  # type: str
    ):
        # type: (...) -> None

        # The RECORD is a csv file with the path to each installed file in the 1st column.
        # See: https://peps.python.org/pep-0376/#record
        with safe_open(dst, "wb" if PY2 else "w") as fp:
            cls.write_fp(fp, installed_files, eol=eol)

    @classmethod
    def read(
        cls,
        lines,  # type: Union[FileInput[Text], Iterator[Text]]
        exclude=None,  # type: Optional[Callable[[Text], bool]]
    ):
        # type: (...) -> Iterator[InstalledFile]

        # The RECORD is a csv file with the path to each installed file in the 1st column.
        # See: https://peps.python.org/pep-0376/#record
        for line, (path, fingerprint, file_size) in enumerate(
            csv.reader(lines, delimiter=",", quotechar='"'), start=1
        ):
            resolved_path = path
            if exclude and exclude(resolved_path):
                continue
            file_hash = Hash(fingerprint) if fingerprint else None
            size = int(file_size) if file_size else None
            yield InstalledFile(path=path, hash=file_hash, size=size)

    project_name = attr.ib()  # type: str
    version = attr.ib()  # type: str
    prefix_dir = attr.ib()  # type: str
    rel_base_dir = attr.ib()  # type: Text
    relative_path = attr.ib()  # type: Text
