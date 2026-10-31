# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import itertools
import os
import shutil
import zipfile
from collections import defaultdict

from pex.common import deterministic_walk, safe_copy, safe_mkdir, safe_relative_symlink, touch
from pex.executables import chmod_plus_x
from pex.modes import Modes
from pex.typing import TYPE_CHECKING
from pex.zipfile import open_zip

if TYPE_CHECKING:
    from typing import Callable, DefaultDict, Dict, Iterable, Iterator, Optional, Set, Tuple, Union


class Chroot(object):
    """A chroot of files overlaid from one directory to another directory.

    Files may be tagged when added in order to keep track of multiple overlays in the chroot.
    """

    class Error(Exception):
        pass

    class ChrootTaggingException(Error):
        pass

    def __init__(self, chroot_base):
        # type: (str) -> None
        """Create the chroot.

        :chroot_base Directory for the creation of the target chroot.
        """
        try:
            safe_mkdir(chroot_base)
        except OSError as e:
            raise self.Error("Unable to create chroot in %s: %s" % (chroot_base, e))
        self.chroot = chroot_base  # type: str
        self.filesets = defaultdict(set)  # type: DefaultDict[Optional[str], Set[str]]
        self._compress_by_file = {}  # type: Dict[str, bool]
        self._file_index = {}  # type: Dict[str, Optional[str]]

    def path(self):
        # type: () -> str
        """The path of the chroot."""
        return self.chroot

    def _normalize(self, dst):
        # type: (str) -> str
        dst = os.path.normpath(dst)
        if dst.startswith(os.sep) or dst.startswith(".."):
            raise self.Error("Destination path is not a relative path!")
        return dst

    def _check_tag(
        self,
        fn,  # type: str
        label,  # type: Optional[str]
        compress=True,  # type: bool
    ):
        # type: (...) -> None
        """Raises ChrootTaggingException if a file was added under more than one label."""
        existing_label = self._file_index.setdefault(fn, label)
        if label != existing_label:
            raise self.ChrootTaggingException(
                "Trying to add {file} to fileset({new_tag}) but already in "
                "fileset({orig_tag})!".format(file=fn, new_tag=label, orig_tag=existing_label)
            )
        existing_compress = self._compress_by_file.setdefault(fn, compress)
        if compress != existing_compress:
            raise self.ChrootTaggingException(
                "Trying to add {file} to fileset({tag}) with compress {new_compress} but already "
                "added with compress {orig_compress}!".format(
                    file=fn, tag=label, new_compress=compress, orig_compress=existing_compress
                )
            )

    def _tag(
        self,
        fn,  # type: str
        label,  # type: Optional[str]
        compress,  # type: bool
    ):
        # type: (...) -> None
        self._check_tag(fn, label, compress)
        self.filesets[label].add(fn)

    def _ensure_parent(self, path):
        # type: (str) -> None
        safe_mkdir(os.path.dirname(os.path.join(self.chroot, path)))

    def copy(
        self,
        src,  # type: str
        dst,  # type: str
        label=None,  # type: Optional[str]
        compress=True,  # type: bool
    ):
        # type: (...) -> None
        """Copy file ``src`` to ``chroot/dst`` with optional label.

        May raise anything shutil.copy can raise, e.g.
          IOError(Errno 21 'EISDIR')

        May raise ChrootTaggingException if dst is already in a fileset
        but with a different label.
        """
        dst = self._normalize(dst)
        self._tag(dst, label, compress)
        self._ensure_parent(dst)
        shutil.copy(src, os.path.join(self.chroot, dst))

    def link(
        self,
        src,  # type: str
        dst,  # type: str
        label=None,  # type: Optional[str]
        compress=True,  # type: bool
    ):
        # type: (...) -> None
        """Hard link file from ``src`` to ``chroot/dst`` with optional label.

        May raise anything os.link can raise, e.g.
          IOError(Errno 21 'EISDIR')

        May raise ChrootTaggingException if dst is already in a fileset
        but with a different label.
        """
        dst = self._normalize(dst)
        self._tag(dst, label, compress)
        self._ensure_parent(dst)
        abs_src = src
        abs_dst = os.path.join(self.chroot, dst)
        safe_copy(abs_src, abs_dst, overwrite=False)
        # TODO: Ensure the target and dest are the same if the file already exists.

    def symlink(
        self,
        src,  # type: str
        dst,  # type: str
        label=None,  # type: Optional[str]
        compress=True,  # type: bool
    ):
        # type: (...) -> None
        dst = self._normalize(dst)
        self._tag(dst, label, compress)
        self._ensure_parent(dst)
        abs_src = os.path.realpath(src)
        abs_dst = os.path.realpath(os.path.join(self.chroot, dst))
        safe_relative_symlink(abs_src, abs_dst)

    def write(
        self,
        data,  # type: Union[str, bytes]
        dst,  # type: str
        label=None,  # type: Optional[str]
        mode="wb",  # type: str
        executable=False,  # type: bool
        compress=True,  # type: bool
    ):
        # type: (...) -> None
        """Write data to ``chroot/dst`` with optional label.

        Has similar exceptional cases as ``Chroot.copy``
        """
        dst = self._normalize(dst)
        self._tag(dst, label, compress)
        self._ensure_parent(dst)
        with open(os.path.join(self.chroot, dst), mode) as wp:
            wp.write(data)
        if executable:
            chmod_plus_x(wp.name)

    def touch(
        self,
        dst,  # type: str
        label=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        """Perform 'touch' on ``chroot/dst`` with optional label.

        Has similar exceptional cases as Chroot.copy
        """
        dst = self._normalize(dst)
        self._tag(dst, label, compress=False)
        touch(os.path.join(self.chroot, dst))

    def get(self, label):
        # type: (Optional[str]) -> Set[str]
        """Get all files labeled with ``label``"""
        return self.filesets.get(label, set())

    def files(self):
        # type: () -> Set[str]
        """Get all files in the chroot."""
        all_files = set()
        for label in self.filesets:
            all_files.update(self.filesets[label])
        return all_files

    def labels(self):
        # type: () -> Iterable[Optional[str]]
        return self.filesets.keys()

    def __str__(self):
        # type: () -> str
        return "Chroot(%s {fs:%s})" % (
            self.chroot,
            " ".join("%s" % foo for foo in self.filesets.keys()),
        )

    def delete(self):
        # type: () -> None
        shutil.rmtree(self.chroot)

    def zip(
        self,
        filename,  # type: str
        mode="w",  # type: str
        deterministic=False,  # type: bool
        exclude_file=lambda _: False,  # type: Callable[[str], bool]
        strip_prefix=None,  # type: Optional[str]
        labels=None,  # type: Optional[Iterable[str]]
        compress=True,  # type: bool
        modes=Modes(),  # type: Optional[Modes]
    ):
        # type: (...) -> None

        if labels:
            selected_files = set(
                itertools.chain.from_iterable(self.filesets.get(label, ()) for label in labels)
            )
        else:
            selected_files = self.files()

        with open_zip(
            filename,
            mode=mode,
            compression=zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED,
            modes=modes,
        ) as zf:

            def write_entry(
                filename,  # type: str
                arcname,  # type: str
            ):
                # type: (...) -> None
                zf.write_deterministic(
                    filename=filename,
                    arcname=os.path.relpath(arcname, strip_prefix) if strip_prefix else arcname,
                    deterministic=deterministic,
                    compress=compress and self._compress_by_file.get(arcname, True),
                )

            def get_parent_dir(path):
                # type: (str) -> Optional[str]
                parent_dir = os.path.normpath(os.path.dirname(path))
                if parent_dir and parent_dir != os.curdir:
                    return parent_dir
                return None

            written_dirs = set()

            def maybe_write_parent_dirs(path):
                # type: (str) -> None
                if path == strip_prefix:
                    return
                parent_dir = get_parent_dir(path)
                if parent_dir is None or parent_dir in written_dirs:
                    return
                maybe_write_parent_dirs(parent_dir)
                if parent_dir != strip_prefix:
                    write_entry(filename=os.path.join(self.chroot, parent_dir), arcname=parent_dir)
                written_dirs.add(parent_dir)

            def iter_files():
                # type: () -> Iterator[Tuple[str, str]]
                for path in sorted(selected_files):
                    full_path = os.path.join(self.chroot, path)
                    if os.path.isfile(full_path):
                        if exclude_file(full_path):
                            continue
                        yield full_path, path
                        continue

                    for root, _, files in deterministic_walk(full_path):
                        for f in files:
                            if exclude_file(f):
                                continue
                            abs_path = os.path.join(root, f)
                            rel_path = os.path.join(path, os.path.relpath(abs_path, full_path))
                            yield abs_path, rel_path

            for filename, arcname in iter_files():
                maybe_write_parent_dirs(arcname)
                write_entry(filename, arcname)
