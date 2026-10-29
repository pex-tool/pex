# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os

from pex.compatibility import to_unicode
from pex.hashing import Sha256, file_hash, locked_directory, update_hash
from pex.typing import TYPE_CHECKING
from pex.zipfile import open_zip

if TYPE_CHECKING:
    from typing import Callable, Iterator, Optional, Text

    from pex.hashing_types import HintedDigest


def dir_hash(
    directory,  # type: Text
    digest,  # type: HintedDigest
    dir_filter=lambda d: True,  # type: Callable[[Text], bool]
    file_filter=lambda f: True,  # type: Callable[[Text], bool]
    followlinks=True,  # type: bool
):
    # type: (...) -> None
    """Digest the contents of a directory in a reproducible manner."""

    with locked_directory(directory) as top:

        def iter_files():
            # type: () -> Iterator[Text]
            for root, dirs, files in os.walk(top, followlinks=followlinks):
                dirs[:] = [
                    d for d in dirs if dir_filter(os.path.relpath(os.path.join(root, d), top))
                ]
                for f in files:
                    path = os.path.join(root, f)
                    if file_filter(os.path.relpath(path, top)):
                        yield path

        file_paths = sorted(iter_files())

        # Regularize to / as the directory separator so that a dir hash on Unix matches a dir hash
        # on Windows matches a zip hash (see below) of that same dir.
        hashed_names = [os.path.relpath(n, top).replace(os.sep, "/") for n in file_paths]
        digest.update(to_unicode("").join(map(to_unicode, hashed_names)).encode("utf-8"))

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

        dirs = set()
        for name in namelist:
            if name.endswith("/"):
                dirname = name.rstrip("/")
            else:
                dirname = os.path.dirname(name)
            while dirname:
                dirs.add(dirname)
                dirname = os.path.dirname(dirname)

        accept_dirs = frozenset(
            d for d in dirs if dir_filter(os.path.relpath(d, relpath) if relpath else d)
        )
        reject_dirs = tuple("{dir}/".format(dir=path) for path in (dirs - accept_dirs))
        accept_files = sorted(
            name
            for name in namelist
            if not name.endswith("/")
            and not name.startswith(reject_dirs)
            and file_filter(os.path.relpath(name, relpath) if relpath else name)
        )

        hashed_names = (
            [os.path.relpath(name, relpath) for name in accept_files] if relpath else accept_files
        )
        digest.update(to_unicode("").join(map(to_unicode, hashed_names)).encode("utf-8"))

        for filename in accept_files:
            update_hash(zf.open(filename, "r"), digest)


if __name__ == "__main__":
    import sys
    import zipfile
    from argparse import ArgumentParser

    from pex.common import is_pyc_dir, is_pyc_file

    parser = ArgumentParser()
    parser.add_argument(
        "--exclude-dir",
        dest="exclude_dirs",
        action="append",
        default=[],
    )
    parser.add_argument("--zip-relpath")
    parser.add_argument("paths", nargs="+")

    options = parser.parse_args()
    exclude_dirs = frozenset(options.exclude_dirs)

    for path in options.paths:
        digest = Sha256()
        if zipfile.is_zipfile(path):
            zip_hash(
                path,
                digest=digest,
                relpath=options.zip_relpath,
                dir_filter=(
                    lambda dir_path: (
                        not is_pyc_dir(dir_path) and os.path.basename(dir_path) not in exclude_dirs
                    )
                ),
                file_filter=lambda f: not is_pyc_file(f),
            )
        elif os.path.isdir(path):
            dir_hash(
                path,
                digest=digest,
                dir_filter=(
                    lambda dir_path: (
                        not is_pyc_dir(dir_path) and os.path.basename(dir_path) not in exclude_dirs
                    )
                ),
                file_filter=lambda f: not is_pyc_file(f),
            )
        else:
            print("Can only hash zip files or directories. Skipping file", path, file=sys.stderr)
        print(path, digest.hexdigest(), file=sys.stdout)
