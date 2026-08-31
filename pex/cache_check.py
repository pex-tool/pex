# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os
import zipimport
from textwrap import dedent
from zipimport import ZipImportError

from pex import hashing, pex_warnings
from pex.enum import Enum
from pex.installed_wheel import InstalledWheel
from pex.layout import Layout
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import Optional


class InvalidZipAppError(Exception):
    pass


class CorruptCacheEntryError(Exception):
    """Indicates a PEX cache entry no longer holds what Pex wrote to it."""


# Records the digest of the zip a cache entry holds. Written inside the `atomic_directory` work dir,
# so it lands through the same atomic rename as the zip it describes.
CACHE_ENTRY_DIGEST = ".pex-cache-entry-digest"


def _cache_entry_matches_digest(
    cache_dir,  # type: str
    relpath,  # type: str
):
    # type: (...) -> bool
    """Check a cache entry against the digest recorded when Pex wrote it.

    An entry carrying no digest was written before Pex recorded them. No claim was made about
    that entry, so none is checked and it is taken as-is.
    """
    zip_path = os.path.join(cache_dir, relpath)
    if not os.path.isfile(zip_path):
        return False

    digest_path = os.path.join(cache_dir, CACHE_ENTRY_DIGEST)
    if not os.path.isfile(digest_path):
        return True

    try:
        with open(digest_path) as digest_fp:
            expected = digest_fp.read().strip()
    except (IOError, OSError):
        return False
    return bool(expected) and expected == CacheHelper.hash(zip_path, hasher=hashing.Sha256)


def _installed_wheel_dir_matches_digest(install_chroot):
    # type: (str) -> bool
    """Check an installed wheel chroot against the fingerprint recorded in its `.layout.json`.

    A chroot with no loadable `.layout.json`, or one with no recorded fingerprint, was written
    before Pex recorded per-chroot fingerprints (or without going through `install_wheel_chroot`
    at all). No claim was made about it, so none is checked and it is taken as-is.
    """
    try:
        installed_wheel = InstalledWheel.load(install_chroot)
    except InstalledWheel.LoadError:
        return True

    if installed_wheel.fingerprint is None:
        return True

    recomputed = CacheHelper.dir_hash(
        install_chroot,
        hasher=hashlib.sha256,
        exclude_files=(InstalledWheel.LAYOUT_JSON_FILENAME,),
    )
    return recomputed == installed_wheel.fingerprint


class Check(Enum["Check.Value"]):
    class Value(Enum.Value):
        def perform_check(
            self,
            layout,  # type: Layout.Value
            path,  # type: str
        ):
            # type: (...) -> Optional[bool]

            if self is Check.NONE:
                return None

            if layout is not Layout.ZIPAPP:
                return None

            try:
                importer = zipimport.zipimporter(path)

                # N.B.: The legacy `find_module` method returns the `zipimporter` instance itself on
                # success and the `find_spec` method returns a `ModuleSpec` instance on success, but
                # both return `None` on failure to find the module.
                finder = "find_spec" if hasattr(importer, "find_spec") else "find_module"
                if getattr(importer, finder)("__main__") is not None:
                    return True
                reason = "Could not find the `__main__` module."
            except ZipImportError as e:
                # N.B.: PyPy<3.8 raises "ZipImportError: <PATH> seems not to be a zipfile" for ZIP64
                # zips; so we handle that here.
                reason = str(e)

            message = (
                dedent(
                    """\
                    The PEX zip at {path} is not a valid zipapp: {reason}
                    This is likely due to the zip requiring ZIP64 extensions due to size or the
                    number of file entries or both. You can work around this limitation in Python's
                    `zipimport` module by re-building the PEX with `--layout packed` or
                    `--layout loose`.
                    """
                )
                .format(path=path, reason=reason)
                .strip()
            )
            if self is Check.ERROR:
                raise InvalidZipAppError(message)

            pex_warnings.warn(message)
            return False

        def verify_cache_entry(
            self,
            cache_dir,  # type: str
            relpath,  # type: str
        ):
            # type: (...) -> bool
            """Return `True` if the cache entry at `relpath` can be trusted for reuse.

            N.B.: Verification reads the cached zip in full. Reusing a cache entry is otherwise
            close to free -- `safe_copy` hard links it into the PEX under construction where the
            platform allows -- so `Check.NONE` skips the read entirely.
            """
            if self is Check.NONE:
                return True

            if _cache_entry_matches_digest(cache_dir, relpath):
                return True

            message = (
                dedent(
                    """\
                    The PEX cache entry at {cache_dir} does not match the digest Pex recorded when
                    it wrote that entry; so it has been modified since. Building {relpath} without
                    the cache for this PEX. Remove that directory to restore caching for it.
                    """
                )
                .format(cache_dir=cache_dir, relpath=relpath)
                .strip()
            )
            if self is Check.ERROR:
                raise CorruptCacheEntryError(message)

            pex_warnings.warn(message)
            return False

        def verify_installed_wheel(
            self,
            install_chroot,  # type: str
        ):
            # type: (...) -> bool
            """Return `True` if the installed wheel chroot at `install_chroot` can be reused.

            N.B.: Verification re-hashes the chroot's contents in full. `Check.NONE` skips the
            read entirely.
            """
            if self is Check.NONE:
                return True

            if _installed_wheel_dir_matches_digest(install_chroot):
                return True

            message = (
                dedent(
                    """\
                    The installed wheel chroot at {install_chroot} does not match the fingerprint
                    Pex recorded when it wrote that chroot; so it has been modified since.
                    Installing without the cache for this wheel. Remove that directory to restore
                    caching for it.
                    """
                )
                .format(install_chroot=install_chroot)
                .strip()
            )
            if self is Check.ERROR:
                raise CorruptCacheEntryError(message)

            pex_warnings.warn(message)
            return False

    NONE = Value("none")
    WARN = Value("warn")
    ERROR = Value("error")


Check.seal()
