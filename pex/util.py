# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import hashlib
import importlib
import os
import shutil
import tempfile
from hashlib import sha1
from site import makepath  # type: ignore[attr-defined]

from pex import hashing
from pex.common import is_pyc_dir, is_pyc_file, safe_mkdir, safe_mkdtemp
from pex.compatibility import (  # type: ignore[attr-defined]  # `exec_function` is defined dynamically
    PY2,
    exec_function,
)
from pex.orderedset import OrderedSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO, Any, Callable, Container, Iterator, Optional, Text

    from pex.hashing import Hasher


class DistributionHelper(object):
    # TODO(#584: This appears unused, but clients might still use it. We cannot remove until we
    #  have a deprecation policy.
    @classmethod
    def access_zipped_assets(cls, static_module_name, static_path, dir_location=None):
        # type: (str, str, Optional[str]) -> str
        """Create a copy of static resource files as we can't serve them from within the pex file.

        :param static_module_name: Module name containing module to cache in a tempdir
        :param static_path: Module name, for example 'serverset'
        :param dir_location: create a new temporary directory inside, or None to have one created
        :returns temp_dir: Temporary directory with the zipped assets inside
        """
        if dir_location is None:
            temp_dir = safe_mkdtemp()
        else:
            temp_dir = dir_location

        module = importlib.import_module(static_module_name)
        # N.B.: This handles namespace packages new and old.
        paths = OrderedSet(os.path.realpath(d) for d in getattr(module, "__path__", []))
        if module.__file__:
            # And this handles old-style __init__.py packages.
            paths.add(os.path.realpath(module.__file__))

        safe_mkdir(temp_dir)
        for path in paths:
            resource_dir = os.path.realpath(os.path.join(path, static_path))
            if os.path.isdir(resource_dir):
                for root, dirs, files in os.walk(resource_dir):
                    for d in dirs:
                        safe_mkdir(
                            os.path.join(
                                temp_dir, os.path.relpath(os.path.join(root, d), resource_dir)
                            )
                        )
                    for f in files:
                        src = os.path.join(root, f)
                        shutil.copy(src, os.path.join(temp_dir, os.path.relpath(src, resource_dir)))
        return temp_dir


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
        hashing.dir_hash(
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
        hashing.dir_hash(
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
        hashing.zip_hash(
            zip_path=zip_path,
            digest=digest,
            relpath=relpath,
            dir_filter=lambda d: not is_pyc_dir(d),
            file_filter=lambda f: not is_pyc_file(f),
        )
        return digest.hexdigest()


@contextlib.contextmanager
def named_temporary_file(**kwargs):
    # type: (**Any) -> Iterator[IO]
    """Due to a bug in python (https://bugs.python.org/issue14243), we need this to be able to use
    the temporary file without deleting it."""
    assert "delete" not in kwargs
    kwargs["delete"] = False
    fp = tempfile.NamedTemporaryFile(**kwargs)
    try:
        with fp:
            yield fp
    finally:
        os.remove(fp.name)
