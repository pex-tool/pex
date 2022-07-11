# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import hashlib
import importlib
import os
import shutil
import sys
import tempfile
from hashlib import sha1
from site import makepath  # type: ignore[attr-defined]
from zipfile import ZipFile

from pex import hashing
from pex.common import atomic_directory, filter_pyc_dirs, filter_pyc_files, safe_mkdir, safe_mkdtemp
from pex.compatibility import (  # type: ignore[attr-defined]  # `exec_function` is defined dynamically
    PY2,
    exec_function,
)
from pex.dist_metadata import Distribution
from pex.orderedset import OrderedSet
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO, Any, Callable, Iterator, Optional

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
        # type: (str, Optional[Hasher], Callable[[], Hasher]) -> str
        """Return the digest of a single file in a memory-efficient manner."""
        if digest is None:
            digest = hasher()
        hashing.file_hash(path, digest)
        return digest.hexdigest()

    @classmethod
    def pex_code_hash(cls, d):
        # type: (str) -> str
        """Return a reproducible hash of the contents of a loose PEX; excluding all `.pyc` files."""
        digest = hashlib.sha1()
        hashing.dir_hash(
            directory=d,
            digest=digest,
            dir_filter=filter_pyc_dirs,
            file_filter=lambda files: (f for f in filter_pyc_files(files) if not f.startswith(".")),
        )
        return digest.hexdigest()

    @classmethod
    def dir_hash(cls, d, digest=None, hasher=sha1):
        # type: (str, Optional[Hasher], Callable[[], Hasher]) -> str
        """Return a reproducible hash of the contents of a directory; excluding all `.pyc` files."""
        if digest is None:
            digest = hasher()
        hashing.dir_hash(
            directory=d, digest=digest, dir_filter=filter_pyc_dirs, file_filter=filter_pyc_files
        )
        return digest.hexdigest()

    @classmethod
    def cache_distribution(cls, zf, source, target_dir):
        # type: (ZipFile, str, str) -> Distribution
        """Possibly cache a wheel from within a zipfile into `target_dir`.

        Given a zipfile handle and a source path prefix corresponding to a wheel install embedded within
        that zip, maybe extract the wheel install into the target cache and then return a distribution
        from the cache.

        :param zf: An open zip file (a zipped pex).
        :param source: The path prefix of a wheel install embedded in the zip file.
        :param target_dir: The directory to cache the distribution in if not already cached.
        :returns: The cached distribution.
        """
        with atomic_directory(target_dir, source=source, exclusive=True) as target_dir_tmp:
            if target_dir_tmp.is_finalized():
                TRACER.log("Using cached {}".format(target_dir), V=3)
            else:
                with TRACER.timed("Caching {}:{} in {}".format(zf.filename, source, target_dir)):
                    for name in zf.namelist():
                        if name.startswith(source) and not name.endswith("/"):
                            zf.extract(name, target_dir_tmp.work_dir)

        return Distribution.load(target_dir)


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


def iter_pth_paths(filename):
    # type: (str) -> Iterator[str]
    """Given a .pth file, extract and yield all inner paths without honoring imports.

    This shadows Python's site.py behavior, which is invoked at interpreter startup.
    """
    try:
        f = open(filename, "rU" if PY2 else "r")  # noqa
    except IOError:
        return

    dirname = os.path.dirname(filename)
    known_paths = set()

    with f:
        for i, line in enumerate(f, start=1):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            elif line.startswith(("import ", "import\t")):
                # One important side effect of executing import lines can be alteration of the
                # sys.path directly or indirectly as a programmatic way to add sys.path entries
                # in contrast to the standard .pth mechanism of including fixed paths as
                # individual lines in the file. Here we capture all such programmatic attempts
                # to expand the sys.path and report the additions.
                original_sys_path = sys.path[:]
                try:
                    # N.B.: Setting sys.path to empty is ok since all the .pth files we find and
                    # execute have already been found and executed by our ambient sys.executable
                    # when it started up before running this PEX file. As such, all symbols imported
                    # by the .pth files then will still be available now as cached in sys.modules.
                    sys.path = []
                    exec_function(line, globals_map={})
                    for path in sys.path:
                        yield path
                except Exception as e:
                    # NB: import lines are routinely abused with extra code appended using `;` so
                    # the class of exceptions that might be raised in broader than ImportError. As
                    # such we catch broadly here.
                    TRACER.log(
                        "Error executing line {linenumber} of {pth_file} with content:\n"
                        "{content}\n"
                        "Error was:\n"
                        "{error}".format(linenumber=i, pth_file=filename, content=line, error=e),
                        V=9,
                    )

                    # Defer error handling to the higher level site.py logic invoked at startup.
                    return
                finally:
                    sys.path = original_sys_path
            else:
                extras_dir, extras_dir_case_insensitive = makepath(dirname, line)
                if extras_dir_case_insensitive not in known_paths and os.path.exists(extras_dir):
                    yield extras_dir
                    known_paths.add(extras_dir_case_insensitive)
