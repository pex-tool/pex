# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import os
import sys
import tempfile
from hashlib import sha1
from site import makepath  # type: ignore[attr-defined]
from zipfile import ZipFile

from pex.common import atomic_directory, safe_mkdir, safe_mkdtemp
from pex.compatibility import (  # type: ignore[attr-defined]  # `exec_function` is defined dynamically
    PY2,
    exec_function,
)
from pex.third_party.pkg_resources import (
    Distribution,
    find_distributions,
    resource_isdir,
    resource_listdir,
    resource_string,
)
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    if PY2:
        from hashlib import _hash as _Hash
    else:
        from hashlib import _Hash
    from typing import Any, Callable, IO, Iterable, Iterator, Optional


class DistributionHelper(object):
    # TODO(#584: This appears unused, but clients might still use it. We cannot remove until we have a deprecation
    # policy.
    @classmethod
    def access_zipped_assets(cls, static_module_name, static_path, dir_location=None):
        # type: (str, str, Optional[str]) -> str
        """Create a copy of static resource files as we can't serve them from within the pex file.

        :param static_module_name: Module name containing module to cache in a tempdir
        :param static_path: Module name, for example 'serverset'
        :param dir_location: create a new temporary directory inside, or None to have one created
        :returns temp_dir: Temporary directory with the zipped assets inside
        """
        # asset_path is initially a module name that's the same as the static_path, but will be
        # changed to walk the directory tree
        # TODO(John Sirois): Unify with `pex.third_party.isolated(recursive_copy)`.
        def walk_zipped_assets(static_module_name, static_path, asset_path, temp_dir):
            for asset in resource_listdir(static_module_name, asset_path):
                if not asset:
                    # The `resource_listdir` function returns a '' asset for the directory entry
                    # itself if it is either present on the filesystem or present as an explicit
                    # zip entry. Since we only care about files and subdirectories at this point,
                    # skip these assets.
                    continue
                asset_target = os.path.normpath(
                    os.path.join(os.path.relpath(asset_path, static_path), asset)
                )
                if resource_isdir(static_module_name, os.path.join(asset_path, asset)):
                    safe_mkdir(os.path.join(temp_dir, asset_target))
                    walk_zipped_assets(
                        static_module_name, static_path, os.path.join(asset_path, asset), temp_dir
                    )
                else:
                    with open(os.path.join(temp_dir, asset_target), "wb") as fp:
                        path = os.path.join(static_path, asset_target)
                        file_data = resource_string(static_module_name, path)
                        fp.write(file_data)

        if dir_location is None:
            temp_dir = safe_mkdtemp()
        else:
            temp_dir = dir_location

        walk_zipped_assets(static_module_name, static_path, static_path, temp_dir)

        return temp_dir

    @classmethod
    def distribution_from_path(cls, path, name=None):
        # type: (str, Optional[str]) -> Optional[Distribution]
        """Return a distribution from a path.

        If name is provided, find the distribution.  If none is found matching the name, return
        None. If name is not provided and there is unambiguously a single distribution, return that
        distribution. Otherwise, None.
        """
        if name is None:
            distributions = set(find_distributions(path))
            if len(distributions) == 1:
                return distributions.pop()
        else:
            for dist in find_distributions(path):
                if dist.project_name == name:
                    return dist
        return None


class CacheHelper(object):
    @classmethod
    def update_hash(cls, filelike, digest):
        # type: (IO[bytes], _Hash) -> None
        """Update the digest of a single file in a memory-efficient manner."""
        block_size = digest.block_size * 1024
        for chunk in iter(lambda: filelike.read(block_size), b""):
            digest.update(chunk)

    @classmethod
    def hash(cls, path, digest=None, hasher=sha1):
        # type: (str, Optional[_Hash], Callable) -> str
        """Return the digest of a single file in a memory-efficient manner."""
        if digest is None:
            digest = hasher()
        with open(path, "rb") as fh:
            cls.update_hash(fh, digest)
        return digest.hexdigest()

    @classmethod
    def _compute_hash(cls, names, stream_factory):
        # type: (Iterable[str], Callable[[str], IO]) -> str
        digest = sha1()
        # Always use / as the path separator, since that's what zip uses.
        hashed_names = [n.replace(os.sep, "/") for n in names]
        digest.update("".join(hashed_names).encode("utf-8"))
        for name in names:
            with contextlib.closing(stream_factory(name)) as fp:
                cls.update_hash(fp, digest)
        return digest.hexdigest()

    @classmethod
    def _iter_files(cls, directory):
        # type: (str) -> Iterator[str]
        normpath = os.path.realpath(os.path.normpath(directory))
        for root, _, files in os.walk(normpath):
            for f in files:
                yield os.path.relpath(os.path.join(root, f), normpath)

    @classmethod
    def pex_hash(cls, d):
        # type: (str) -> str
        """Return a reproducible hash of the contents of a directory."""
        names = sorted(
            f for f in cls._iter_files(d) if not (f.endswith(".pyc") or f.startswith("."))
        )

        def stream_factory(name):
            # type: (str) -> IO
            return open(os.path.join(d, name), "rb")  # noqa: T802

        return cls._compute_hash(names, stream_factory)

    @classmethod
    def dir_hash(cls, d):
        # type: (str) -> str
        """Return a reproducible hash of the contents of a directory."""
        names = sorted(f for f in cls._iter_files(d) if not f.endswith(".pyc"))

        def stream_factory(name):
            # type: (str) -> IO
            return open(os.path.join(d, name), "rb")  # noqa: T802

        return cls._compute_hash(names, stream_factory)

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
            if target_dir_tmp is None:
                TRACER.log("Using cached {}".format(target_dir))
            else:
                with TRACER.timed("Caching {}:{} in {}".format(zf.filename, source, target_dir)):
                    for name in zf.namelist():
                        if name.startswith(source) and not name.endswith("/"):
                            zf.extract(name, target_dir_tmp)

        dist = DistributionHelper.distribution_from_path(target_dir)
        assert dist is not None, "Failed to cache distribution: {} ".format(source)
        return dist


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
