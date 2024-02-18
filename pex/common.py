# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import atexit
import contextlib
import errno
import itertools
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
from datetime import datetime
from uuid import uuid4

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        Container,
        DefaultDict,
        Dict,
        Iterable,
        Iterator,
        List,
        NoReturn,
        Optional,
        Set,
        Sized,
        Text,
        Tuple,
        Union,
    )


# We use the start of MS-DOS time, which is what zipfiles use (see section 4.4.6 of
# https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT).
DETERMINISTIC_DATETIME = datetime(
    year=1980, month=1, day=1, hour=0, minute=0, second=0, tzinfo=None
)
_UNIX_EPOCH = datetime(year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=None)
DETERMINISTIC_DATETIME_TIMESTAMP = (DETERMINISTIC_DATETIME - _UNIX_EPOCH).total_seconds()


def is_pyc_dir(dir_path):
    # type: (Text) -> bool
    """Return `True` if `dir_path` is a Python bytecode cache directory."""
    return os.path.basename(dir_path) == "__pycache__"


def is_pyc_file(file_path):
    # type: (Text) -> bool
    """Return `True` if `file_path` is a Python bytecode file."""
    # N.B.: For Python 2.7, `.pyc` files are compiled as siblings to `.py` files (there is no
    # __pycache__ dir).
    return file_path.endswith((".pyc", ".pyo")) or is_pyc_temporary_file(file_path)


def is_pyc_temporary_file(file_path):
    # type: (Text) -> bool
    """Check if `file` is a temporary Python bytecode file."""
    # We rely on the fact that the temporary files created by CPython have object id (integer)
    # suffixes to avoid picking up files where Python bytecode compilation is in-flight; i.e.:
    # `.pyc.0123456789`-style files.
    return re.search(r"\.pyc\.[0-9]+$", file_path) is not None


def die(msg, exit_code=1):
    # type: (str, int) -> NoReturn
    print(msg, file=sys.stderr)
    sys.exit(exit_code)


def pluralize(
    subject,  # type: Union[int, Sized]
    noun,  # type: str
):
    # type: (...) -> str
    if noun == "":
        return ""
    count = subject if isinstance(subject, int) else len(subject)
    if count == 1:
        return noun
    if noun[-1] in ("s", "x", "z") or noun[-2:] in ("sh", "ch"):
        return noun + "es"
    else:
        return noun + "s"


def safe_copy(source, dest, overwrite=False):
    # type: (Text, Text, bool) -> None
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
                # See also https://github.com/pex-tool/pex/issues/850 where this was discovered.
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
            self._rmtree(td, ignore_errors=True)


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
        if info.external_attr > 0xFFFF:
            attr = info.external_attr >> 16
            os.chmod(path, attr)


@contextlib.contextmanager
def open_zip(path, *args, **kwargs):
    # type: (Text, *Any, **Any) -> Iterator[PermPreservingZipFile]
    """A contextmanager for zip files.

    Passes through positional and kwargs to zipfile.ZipFile.
    """

    # allowZip64=True is the default in Python 3.4+ but not in 2.7. We uniformly enable Zip64
    # extensions across all Pex supported Pythons.
    kwargs.setdefault("allowZip64", True)

    with contextlib.closing(PermPreservingZipFile(path, *args, **kwargs)) as zip:
        yield zip


def deterministic_walk(*args, **kwargs):
    # type: (*Any, **Any) -> Iterator[Tuple[str, List[str], List[str]]]
    """Walk the specified directory tree in deterministic order.

    Takes the same parameters as os.walk and yields tuples of the same shape,
    except for the `topdown` parameter, which must always be true.
    `deterministic_walk` is essentially a wrapper of os.walk, and os.walk doesn't
    allow modifying the order of the walk when called with `topdown` set to false.

    os.walk uses os.listdir or os.scandir, depending on the Python version,
    both of which don't guarantee the order in which directory entries get listed.
    So when the build output depends on the order of directory traversal,
    use deterministic_walk instead.
    """
    # when topdown is false, modifying ``dirs`` has no effect
    assert kwargs.get("topdown", True), "Determinism cannot be guaranteed when ``topdown`` is false"
    for root, dirs, files in os.walk(*args, **kwargs):
        dirs.sort()
        files.sort()
        yield root, dirs, files
        # make sure ``dirs`` is sorted after any modifications
        dirs.sort()


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
    # type: (Text, bool) -> Text
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
    finally:
        return directory


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
    # type: (Text) -> None
    """Delete a file safely.

    If it's not present, no-op.
    """
    try:
        os.unlink(filename)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


def safe_rmtree(directory):
    # type: (Text) -> None
    """Delete a directory if it's present.

    If it's not present, no-op.
    """
    if os.path.exists(directory):
        shutil.rmtree(directory, True)


def safe_sleep(seconds):
    # type: (float) -> None
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


def chmod_plus_x(path):
    # type: (Text) -> None
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
    :return: `True if the given path is a file executable by the current user.
    """
    return os.path.isfile(path) and os.access(path, os.R_OK | os.X_OK)


def is_script(
    path,  # type: str
    pattern=None,  # type: Optional[str]
    check_executable=True,  # type: bool
):
    # type: (...) -> bool
    """Determines if the given path is a script.

    A script is a file that starts with a shebang (#!...) line.

    :param path: The path to check.
    :param pattern: An optional pattern to match against the shebang (excluding the leading #!).
    :param check_executable: Check that the script is executable by the current user.
    :return: True if the given path is a script.
    """
    if check_executable and not is_exe(path):
        return False
    with open(path, "rb") as fp:
        if b"#!" != fp.read(2):
            return False
        if not pattern:
            return True
        return bool(re.match(pattern, fp.readline().decode("utf-8")))


def is_python_script(
    path,  # type: str
    check_executable=True,  # type: bool
):
    # type: (...) -> bool
    return is_script(path, pattern=r"(?i)^.*(?:python|pypy)", check_executable=check_executable)


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
    # type: (Text) -> None
    """Equivalent of unix `touch path`."""
    with safe_open(file, "a"):
        os.utime(file, None)


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

    def clone(self, into=None):
        # type: (Optional[str]) -> Chroot
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
        abs_src = os.path.abspath(src)
        abs_dst = os.path.join(self.chroot, dst)
        os.symlink(abs_src, abs_dst)

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
        deterministic_timestamp=False,  # type: bool
        exclude_file=lambda _: False,  # type: Callable[[str], bool]
        strip_prefix=None,  # type: Optional[str]
        labels=None,  # type: Optional[Iterable[str]]
        compress=True,  # type: bool
    ):
        # type: (...) -> None

        if labels:
            selected_files = set(
                itertools.chain.from_iterable(self.filesets.get(label, ()) for label in labels)
            )
        else:
            selected_files = self.files()

        with open_zip(
            filename, mode, zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
        ) as zf:

            def write_entry(
                filename,  # type: str
                arcname,  # type: str
            ):
                # type: (...) -> None
                zip_entry = zf.zip_entry_from_file(
                    filename=filename,
                    arcname=os.path.relpath(arcname, strip_prefix) if strip_prefix else arcname,
                    date_time=DETERMINISTIC_DATETIME.timetuple()
                    if deterministic_timestamp
                    else None,
                )
                compress_file = compress and self._compress_by_file.get(arcname, True)
                compression = zipfile.ZIP_DEFLATED if compress_file else zipfile.ZIP_STORED
                zf.writestr(zip_entry.info, zip_entry.data, compression)

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


def relative_symlink(
    src,  # type: Text
    dst,  # type: Text
):
    # type: (...) -> None
    """Creates a symlink to `src` at `dst` using the relative path to `src` from `dst`.

    :param src: The target of the symlink.
    :param dst: The path to create the symlink at.
    """
    dst_parent = os.path.dirname(dst)
    rel_src = os.path.relpath(src, dst_parent)
    os.symlink(rel_src, dst)


def iter_copytree(
    src,  # type: Text
    dst,  # type: Text
    exclude=(),  # type: Container[Text]
    symlink=False,  # type: bool
):
    # type: (...) -> Iterator[Tuple[Text, Text]]
    """Copies the directory tree rooted at `src` to `dst` yielding a tuple for each copied file.

    When not using symlinks, if hard links are appropriate they will be used; otherwise files are
    copied.

    N.B.: The returned iterator must be consumed to drive the copying operations to completion.

    :param src: The source directory tree to copy.
    :param dst: The destination location to copy the source tree to.
    :param exclude: Names (basenames) of files and directories to exclude from copying.
    :param symlink: Whether to use symlinks instead of copies (or hard links).
    :return: An iterator over tuples identifying the copied files of the form `(src, dst)`.
    """
    safe_mkdir(dst)
    link = True
    for root, dirs, files in os.walk(src, topdown=True, followlinks=True):
        if src == root:
            dirs[:] = [d for d in dirs if d not in exclude]
            files[:] = [f for f in files if f not in exclude]

        for path, is_dir in itertools.chain(
            zip(dirs, itertools.repeat(True)), zip(files, itertools.repeat(False))
        ):
            src_entry = os.path.join(root, path)
            dst_entry = os.path.join(dst, os.path.relpath(src_entry, src))
            if not is_dir:
                yield src_entry, dst_entry
            try:
                if symlink:
                    relative_symlink(src_entry, dst_entry)
                elif is_dir:
                    os.mkdir(dst_entry)
                else:
                    # We only try to link regular files since linking a symlink on Linux can produce
                    # another symlink, which leaves open the possibility the src_entry target could
                    # later go missing leaving the dst_entry dangling.
                    if link and not os.path.islink(src_entry):
                        try:
                            os.link(src_entry, dst_entry)
                            continue
                        except OSError as e:
                            if e.errno != errno.EXDEV:
                                raise e
                            link = False
                    shutil.copy(src_entry, dst_entry)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise e

        if symlink:
            # Once we've symlinked the top-level directories and files, we've "copied" everything.
            return
