# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os
from hashlib import sha1

from pex import files_hash, hashing
from pex.common import is_pyc_dir, is_pyc_file
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Container, Optional, Text

    from pex.hashing_types import Hasher


class CacheHelper(object):
    @classmethod
    def hash(cls, path, digest=None, hasher=sha1):
        # type: (Text, Optional[Hasher], Callable[[], Hasher]) -> str
        """Return the digest of a single file in a memory-efficient manner."""
        if digest is None:
            digest = hasher()
        hashing.file_hash(path, digest)
        return digest.hexdigest()

    @classmethod
    def pex_code_hash(
        cls,
        directory,
        exclude_dirs=(),  # type: Container[str]
        exclude_files=(),  # type: Container[str]
    ):
        # type: (...) -> str
        """Return a reproducible hash of the user code of a loose PEX; excluding all `.pyc` files.

        If no code is found, `None` is returned.
        """
        digest = hashlib.sha1()
        files_hash.dir_hash(
            directory=directory,
            digest=digest,
            dir_filter=lambda d: not is_pyc_dir(d) and d not in exclude_dirs,
            file_filter=(
                lambda f: (
                    not is_pyc_file(f)
                    and not os.path.basename(f).startswith(".")
                    and f not in exclude_files
                )
            ),
        )
        return digest.hexdigest()

    @classmethod
    def dir_hash(cls, directory, digest=None, hasher=sha1):
        # type: (str, Optional[Hasher], Callable[[], Hasher]) -> str
        """Return a reproducible hash of the contents of a directory; excluding all `.pyc` files."""
        if digest is None:
            digest = hasher()
        files_hash.dir_hash(
            directory=directory,
            digest=digest,
            dir_filter=lambda d: not is_pyc_dir(d),
            file_filter=lambda f: not is_pyc_file(f),
        )
        return digest.hexdigest()

    @classmethod
    def zip_hash(
        cls,
        zip_path,  # type: str
        relpath=None,  # type: Optional[str]
    ):
        # type: (...) -> str
        """Return a reproducible hash of the contents of a zip; excluding all `.pyc` files."""
        digest = hashlib.sha1()
        files_hash.zip_hash(
            zip_path=zip_path,
            digest=digest,
            relpath=relpath,
            dir_filter=lambda d: not is_pyc_dir(d),
            file_filter=lambda f: not is_pyc_file(f),
        )
        return digest.hexdigest()
