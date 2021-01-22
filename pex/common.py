# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import atexit
import contextlib
import errno
import fcntl
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
import zipfile
from collections import defaultdict, namedtuple
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, DefaultDict, Iterable, Iterator, NoReturn, Optional, Set, Sized

# We use the start of MS-DOS time, which is what zipfiles use (see section 4.4.6 of
# https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT).
DETERMINISTIC_DATETIME = datetime(
    year=1980, month=1, day=1, hour=0, minute=0, second=0, tzinfo=None
)


def filter_pyc_dirs(dirs):
    # type: (Iterable[str]) -> Iterator[str]
    """Return an iterator over the input `dirs` filtering out Python bytecode cache directories."""
    for d in dirs:
        if d != "__pycache__":
            yield d


def filter_pyc_files(files):
    # type: (Iterable[str]) -> Iterator[str]
    """Return an iterator over the input `files` filtering out any Python bytecode files."""
    for f in files:
        # For Python 2.7, `.pyc` files are compiled as siblings to `.py` files (there is no
        # __pycache__ dir). We rely on the fact that the temporary files created by CPython
        # have object id (integer) suffixes to avoid picking up either finished `.pyc` files
        # or files where Python bytecode compilation is in-flight; i.e.:
        # `.pyc.0123456789`-style files.
        if not re.search(r"\.pyc(?:\.[0-9]+)?$", f):
            yield f


def die(msg, exit_code=1):
    # type: (str, int) -> NoReturn
    print(msg, file=sys.stderr)
    sys.exit(exit_code)


def pluralize(
    subject,  # type: Sized
    noun,  # type: str
):
    # type: (...) -> str
    if noun == "":
        return ""
    count = len(subject)
    if count == 1:
        return noun
    if noun[-1] in ("s", "x", "z") or noun[-2:] in ("sh", "ch"):
        return noun + "es"
    else:
        return noun + "s"


def safe_copy(source, dest, overwrite=False):
    # type: (str, str, bool) -> None
    def do_copy():
        # type: () -> None
        temp_dest = dest + uuid4().hex
        shutil.copy(source, temp_dest)
        os.rename(temp_dest, dest)

    # If the platform supports hard-linking, use that and fall back to copying.
    # Windows does not support hard-linking.
    if hasattr(os, "link"):
        try:
            os.link(source, dest)
        except OSError as e:
            if e.errno == errno.EEXIST:
                # File already exists.  If overwrite=True, write otherwise skip.
                if overwrite:
                    do_copy()
            elif e.errno in (errno.EPERM, errno.EXDEV):
                # For a hard link across devices issue, fall back on copying.
                #
                # For a permission issue, the cause could be one of:
                # 1. We can't read source.
                # 2. We can't write dest.
                # 3. We don't own source but can read it.
                # Although we can't do anything about cases 1 and 2, case 3 is due to
                # `protected_hardlinks` (see: https://www.kernel.org/doc/Documentation/sysctl/fs.txt) and
                # we can fall back to copying in that case.
                #
                # See also https://github.com/pantsbuild/pex/issues/850 where this was discovered.
                do_copy()
            else:
                raise
    elif os.path.exists(dest):
        if overwrite:
            do_copy()
    else:
        do_copy()


# See http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
class MktempTeardownRegistry(object):
    def __init__(self):
        # type: () -> None
        self._registry = defaultdict(set)  # type: DefaultDict[int, Set[str]]
        self._lock = threading.RLock()
        self._getpid = os.getpid
        self._exists = os.path.exists
        self._rmtree = shutil.rmtree
        atexit.register(self.teardown)

    def __del__(self):
        # type: () -> None
        self.teardown()

    def register(self, path):
        # type: (str) -> str
        with self._lock:
            self._registry[self._getpid()].add(path)
        return path

    def teardown(self):
        # type: () -> None
        for td in self._registry.pop(self._getpid(), []):
            if self._exists(td):
                self._rmtree(td)


_MKDTEMP_SINGLETON = MktempTeardownRegistry()


class PermPreservingZipFile(zipfile.ZipFile, object):
    """A ZipFile that works around https://bugs.python.org/issue15795."""

    class ZipEntry(namedtuple("ZipEntry", ["info", "data"])):
        pass

    @classmethod
    def zip_entry_from_file(cls, filename, arcname=None, date_time=None):
        """Construct a ZipEntry for a file on the filesystem.

        Usually a similar `zip_info_from_file` method is provided by `ZipInfo`, but it is not
        implemented in Python 2.7 so we re-implement it here to construct the `info` for `ZipEntry`
        adding the possibility to control the `ZipInfo` date_time separately from the underlying
        file mtime. See https://github.com/python/cpython/blob/master/Lib/zipfile.py#L495.
        """
        st = os.stat(filename)
        isdir = stat.S_ISDIR(st.st_mode)
        if arcname is None:
            arcname = filename
        arcname = os.path.normpath(os.path.splitdrive(arcname)[1])
        while arcname[0] in (os.sep, os.altsep):
            arcname = arcname[1:]
        if isdir:
            arcname += "/"
        if date_time is None:
            date_time = time.localtime(st.st_mtime)
        zinfo = zipfile.ZipInfo(filename=arcname, date_time=date_time[:6])
        zinfo.external_attr = (st.st_mode & 0xFFFF) << 16  # Unix attributes
        if isdir:
            zinfo.file_size = 0
            zinfo.external_attr |= 0x10  # MS-DOS directory flag
            zinfo.compress_type = zipfile.ZIP_STORED
            data = b""
        else:
            zinfo.file_size = st.st_size
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            with open(filename, "rb") as fp:
                data = fp.read()
        return cls.ZipEntry(info=zinfo, data=data)

    def _extract_member(self, member, targetpath, pwd):
        result = super(PermPreservingZipFile, self)._extract_member(member, targetpath, pwd)
        info = member if isinstance(member, zipfile.ZipInfo) else self.getinfo(member)
        self._chmod(info, result)
        return result

    def _chmod(self, info, path):
        # This magic works to extract perm bits from the 32 bit external file attributes field for
        # unix-created zip files, for the layout, see:
        #   https://www.forensicswiki.org/wiki/ZIP#External_file_attributes
        attr = info.external_attr >> 16
        os.chmod(path, attr)


@contextlib.contextmanager
def open_zip(path, *args, **kwargs):
    """A contextmanager for zip files.

    Passes through positional and kwargs to zipfile.ZipFile.
    """
    with contextlib.closing(PermPreservingZipFile(path, *args, **kwargs)) as zip:
        yield zip


@contextlib.contextmanager
def temporary_dir(cleanup=True):
    # type: (bool) -> Iterator[str]
    td = tempfile.mkdtemp()
    try:
        yield td
    finally:
        if cleanup:
            safe_rmtree(td)


def safe_mkdtemp(**kw):
    # type: (**Any) -> str
    """Create a temporary directory that is cleaned up on process exit.

    Takes the same parameters as tempfile.mkdtemp.
    """
    # proper lock sanitation on fork [issue 6721] would be desirable here.
    return _MKDTEMP_SINGLETON.register(tempfile.mkdtemp(**kw))


def register_rmtree(directory):
    # type: (str) -> str
    """Register an existing directory to be cleaned up at process exit."""
    return _MKDTEMP_SINGLETON.register(directory)


def safe_mkdir(directory, clean=False):
    # type: (str, bool) -> None
    """Safely create a directory.

    Ensures a directory is present.  If it's not there, it is created.  If it is, it's a no-op. If
    clean is True, ensures the directory is empty.
    """
    if clean:
        safe_rmtree(directory)
    try:
        os.makedirs(directory)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def safe_open(filename, *args, **kwargs):
    """Safely open a file.

    ``safe_open`` ensures that the directory components leading up the specified file have been
    created first.
    """
    parent_dir = os.path.dirname(filename)
    if parent_dir:
        safe_mkdir(parent_dir)
    return open(filename, *args, **kwargs)  # noqa: T802


def safe_delete(filename):
    # type: (str) -> None
    """Delete a file safely.

    If it's not present, no-op.
    """
    try:
        os.unlink(filename)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


def safe_rmtree(directory):
    # type: (str) -> None
    """Delete a directory if it's present.

    If it's not present, no-op.
    """
    if os.path.exists(directory):
        shutil.rmtree(directory, True)


def safe_sleep(seconds):
    # type: (int) -> None
    """Ensure that the thread sleeps at a minimum the requested seconds.

    Until Python 3.5, there was no guarantee that time.sleep() would actually sleep the requested
    time. See https://docs.python.org/3/library/time.html#time.sleep.
    """
    if sys.version_info[0:2] >= (3, 5):
        time.sleep(seconds)
    else:
        start_time = current_time = time.time()
        while current_time - start_time < seconds:
            remaining_time = seconds - (current_time - start_time)
            time.sleep(remaining_time)
            current_time = time.time()


class AtomicDirectory(object):
    def __init__(self, target_dir):
        # type: (str) -> None
        self._target_dir = target_dir
        self._work_dir = "{}.{}".format(target_dir, uuid4().hex)

    @property
    def work_dir(self):
        # type: () -> str
        return self._work_dir

    @property
    def target_dir(self):
        # type: () -> str
        return self._target_dir

    @property
    def is_finalized(self):
        # type: () -> bool
        return os.path.exists(self._target_dir)

    def finalize(self, source=None):
        # type: (Optional[str]) -> None
        """Rename `work_dir` to `target_dir` using `os.rename()`.

        :param source: An optional source offset into the `work_dir`` to use for the atomic update
                       of `target_dir`. By default the whole `work_dir` is used.

        If a race is lost and `target_dir` already exists, the `target_dir` dir is left unchanged and
        the `work_dir` directory will simply be removed.
        """
        if self.is_finalized:
            return

        source = os.path.join(self._work_dir, source) if source else self._work_dir
        try:
            # Perform an atomic rename.
            #
            # Per the docs: https://docs.python.org/2.7/library/os.html#os.rename
            #
            #   The operation may fail on some Unix flavors if src and dst are on different filesystems.
            #   If successful, the renaming will be an atomic operation (this is a POSIX requirement).
            #
            # We have satisfied the single filesystem constraint by arranging the `work_dir` to be a
            # sibling of the `target_dir`.
            os.rename(source, self._target_dir)
        except OSError as e:
            if e.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise e
        finally:
            self.cleanup()

    def cleanup(self):
        # type: () -> None
        safe_rmtree(self._work_dir)


@contextmanager
def atomic_directory(target_dir, exclusive, source=None):
    # type: (str, bool, Optional[str]) -> Iterator[Optional[str]]
    """A context manager that yields a new empty work directory path it will move to `target_dir`.

    :param target_dir: The target directory to atomically update.
    :param exclusive: If `True`, its guaranteed that only one process will be yielded a non `None`
                      workdir; otherwise two or more processes might be yielded unique non-`None`
                      workdirs with the last process to finish "winning".
    :param source: An optional source offset into the work directory to use for the atomic update
                   of the target directory. By default the whole work directory is used.

    If the `target_dir` already exists the enclosed block will be yielded `None` to signal there is
    no work to do.

    If the enclosed block fails the `target_dir` will be undisturbed.

    The new work directory will be cleaned up regardless of whether or not the enclosed block
    succeeds.

    If the contents of the resulting directory will be subsequently mutated it's probably correct to
    pass `exclusive=True` to ensure mutations that race the creation process are not lost.
    """
    atomic_dir = AtomicDirectory(target_dir=target_dir)
    if atomic_dir.is_finalized:
        # Our work is already done for us so exit early.
        yield None
        return

    lock_fd = None  # type: Optional[int]

    def unlock():
        # type: () -> None
        if lock_fd is None:
            return
        try:
            fcntl.lockf(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    if exclusive:
        head, tail = os.path.split(atomic_dir.target_dir)
        if head:
            safe_mkdir(head)
        # N.B.: We don't actually write anything to the lock file but the fcntl file locking
        # operations only work on files opened for at least write.
        lock_fd = os.open(
            os.path.join(head, ".{}.atomic_directory.lck".format(tail or "here")),
            os.O_CREAT | os.O_WRONLY,
        )
        # N.B.: Since lockf operates on an open file descriptor and these are guaranteed to be
        # closed by the operating system when the owning process exits, this lock is immune to
        # staleness.
        fcntl.lockf(lock_fd, fcntl.LOCK_EX)  # A blocking write lock.
        if atomic_dir.is_finalized:
            # We lost the double-checked locking race and our work was done for us by the race
            # winner so exit early.
            try:
                yield None
            finally:
                unlock()
            return

    try:
        safe_mkdir(atomic_dir.work_dir)
        yield atomic_dir.work_dir
        atomic_dir.finalize(source=source)
    finally:
        unlock()
        atomic_dir.cleanup()


def chmod_plus_x(path):
    # type: (str) -> None
    """Equivalent of unix `chmod a+x path`"""
    path_mode = os.stat(path).st_mode
    path_mode &= int("777", 8)
    if path_mode & stat.S_IRUSR:
        path_mode |= stat.S_IXUSR
    if path_mode & stat.S_IRGRP:
        path_mode |= stat.S_IXGRP
    if path_mode & stat.S_IROTH:
        path_mode |= stat.S_IXOTH
    os.chmod(path, path_mode)


def chmod_plus_w(path):
    # type: (str) -> None
    """Equivalent of unix `chmod +w path`"""
    path_mode = os.stat(path).st_mode
    path_mode &= int("777", 8)
    path_mode |= stat.S_IWRITE
    os.chmod(path, path_mode)


def is_exe(path):
    # type: (str) -> bool
    """Determines if the given path is a file executable by the current user.

    :param path: The path to check.
    :return: `True if the given path is an file executable by the current user.
    """
    return os.path.isfile(path) and os.access(path, os.R_OK | os.X_OK)


def can_write_dir(path):
    # type: (str) -> bool
    """Determines if the directory at path can be written to by the current process.

    If the directory doesn't exist, determines if it can be created and thus written to.

    N.B.: This is a best-effort check only that uses permission heuristics and does not actually test
    that the directory can be written to with and writes.

    :param path: The directory path to test.
    :return:`True` if the given path is a directory that can be written to by the current process.
    """
    while not os.access(path, os.F_OK):
        parent_path = os.path.dirname(path)
        if not parent_path or (parent_path == path):
            # We've recursed up to the root without success, which shouldn't happen,
            return False
        path = parent_path
    return os.path.isdir(path) and os.access(path, os.R_OK | os.W_OK | os.X_OK)


def touch(file):
    # type: (str) -> None
    """Equivalent of unix `touch path`."""
    with safe_open(file, "a"):
        os.utime(file, None)


class Chroot(object):
    """A chroot of files overlayed from one directory to another directory.

    Files may be tagged when added in order to keep track of multiple overlays in the chroot.
    """

    class Error(Exception):
        pass

    class ChrootTaggingException(Error):
        def __init__(self, filename, orig_tag, new_tag):
            super(Chroot.ChrootTaggingException, self).__init__(  # noqa: T800
                "Trying to add %s to fileset(%s) but already in fileset(%s)!"
                % (filename, new_tag, orig_tag)
            )

    def __init__(self, chroot_base):
        """Create the chroot.

        :chroot_base Directory for the creation of the target chroot.
        """
        try:
            safe_mkdir(chroot_base)
        except OSError as e:
            raise self.ChrootException("Unable to create chroot in %s: %s" % (chroot_base, e))
        self.chroot = chroot_base
        self.filesets = defaultdict(set)

    def clone(self, into=None):
        """Clone this chroot.

        :keyword into: (optional) An optional destination directory to clone the
          Chroot into.  If not specified, a temporary directory will be created.

        .. versionchanged:: 0.8
          The temporary directory created when ``into`` is not specified is now garbage collected on
          interpreter exit.
        """
        into = into or safe_mkdtemp()
        new_chroot = Chroot(into)
        for label, fileset in self.filesets.items():
            for fn in fileset:
                new_chroot.link(os.path.join(self.chroot, fn), fn, label=label)
        return new_chroot

    def path(self):
        """The path of the chroot."""
        return self.chroot

    def _normalize(self, dst):
        dst = os.path.normpath(dst)
        if dst.startswith(os.sep) or dst.startswith(".."):
            raise self.Error("Destination path is not a relative path!")
        return dst

    def _check_tag(self, fn, label):
        for fs_label, fs in self.filesets.items():
            if fn in fs and fs_label != label:
                raise self.ChrootTaggingException(fn, fs_label, label)

    def _tag(self, fn, label):
        self._check_tag(fn, label)
        self.filesets[label].add(fn)

    def _ensure_parent(self, path):
        safe_mkdir(os.path.dirname(os.path.join(self.chroot, path)))

    def copy(self, src, dst, label=None):
        """Copy file ``src`` to ``chroot/dst`` with optional label.

        May raise anything shutil.copy can raise, e.g.
          IOError(Errno 21 'EISDIR')

        May raise ChrootTaggingException if dst is already in a fileset
        but with a different label.
        """
        dst = self._normalize(dst)
        self._tag(dst, label)
        self._ensure_parent(dst)
        shutil.copy(src, os.path.join(self.chroot, dst))

    def link(self, src, dst, label=None):
        """Hard link file from ``src`` to ``chroot/dst`` with optional label.

        May raise anything os.link can raise, e.g.
          IOError(Errno 21 'EISDIR')

        May raise ChrootTaggingException if dst is already in a fileset
        but with a different label.
        """
        dst = self._normalize(dst)
        self._tag(dst, label)
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
    ):
        # type: (...) -> None
        dst = self._normalize(dst)
        self._tag(dst, label)
        self._ensure_parent(dst)
        abs_src = os.path.abspath(src)
        abs_dst = os.path.join(self.chroot, dst)
        os.symlink(abs_src, abs_dst)

    def write(self, data, dst, label=None, mode="wb"):
        """Write data to ``chroot/dst`` with optional label.

        Has similar exceptional cases as ``Chroot.copy``
        """
        dst = self._normalize(dst)
        self._tag(dst, label)
        self._ensure_parent(dst)
        with open(os.path.join(self.chroot, dst), mode) as wp:
            wp.write(data)

    def touch(self, dst, label=None):
        """Perform 'touch' on ``chroot/dst`` with optional label.

        Has similar exceptional cases as Chroot.copy
        """
        dst = self._normalize(dst)
        self._tag(dst, label)
        touch(os.path.join(self.chroot, dst))

    def get(self, label):
        """Get all files labeled with ``label``"""
        return self.filesets.get(label, set())

    def files(self):
        """Get all files in the chroot."""
        all_files = set()
        for label in self.filesets:
            all_files.update(self.filesets[label])
        return all_files

    def labels(self):
        return self.filesets.keys()

    def __str__(self):
        return "Chroot(%s {fs:%s})" % (
            self.chroot,
            " ".join("%s" % foo for foo in self.filesets.keys()),
        )

    def delete(self):
        shutil.rmtree(self.chroot)

    def zip(self, filename, mode="w", deterministic_timestamp=False):
        with open_zip(filename, mode) as zf:

            def write_entry(filename, arcname):
                zip_entry = zf.zip_entry_from_file(
                    filename=filename,
                    arcname=arcname,
                    date_time=DETERMINISTIC_DATETIME.timetuple()
                    if deterministic_timestamp
                    else None,
                )
                zf.writestr(zip_entry.info, zip_entry.data)

            def get_parent_dir(path):
                parent_dir = os.path.normpath(os.path.dirname(path))
                if parent_dir and parent_dir != os.curdir:
                    return parent_dir
                return None

            written_dirs = set()

            def maybe_write_parent_dirs(path):
                parent_dir = get_parent_dir(path)
                if parent_dir is None or parent_dir in written_dirs:
                    return
                maybe_write_parent_dirs(parent_dir)
                write_entry(filename=os.path.join(self.chroot, parent_dir), arcname=parent_dir)
                written_dirs.add(parent_dir)

            def iter_files():
                for path in sorted(self.files()):
                    full_path = os.path.join(self.chroot, path)
                    if os.path.isfile(full_path):
                        yield full_path, path
                        continue
                    for root, _, files in os.walk(full_path):
                        for f in files:
                            abs_path = os.path.join(root, f)
                            rel_path = os.path.join(path, os.path.relpath(abs_path, full_path))
                            yield abs_path, rel_path

            for filename, arcname in iter_files():
                maybe_write_parent_dirs(arcname)
                write_entry(filename, arcname)
