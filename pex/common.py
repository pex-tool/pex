# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

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
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from pex import atexit
from pex.enum import Enum
from pex.fs import safe_link, safe_rename, safe_symlink
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import (
        Any,
        Container,
        DefaultDict,
        Iterator,
        List,
        NoReturn,
        Optional,
        Set,
        Sized,
        Text,
        Tuple,
        TypeVar,
        Union,
    )

    _Text = TypeVar("_Text", bytes, str, Text)


# We use the start of MS-DOS time, which is what zipfiles use (see section 4.4.6 of
# https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT).
DETERMINISTIC_DATETIME = datetime(
    year=1980, month=1, day=1, hour=0, minute=0, second=0, tzinfo=None
)
_UNIX_EPOCH = datetime(year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=None)
DETERMINISTIC_DATETIME_TIMESTAMP = int((DETERMINISTIC_DATETIME - _UNIX_EPOCH).total_seconds())

# N.B.: The `SOURCE_DATE_EPOCH` env var is semi-standard magic for controlling
# build tools. Wheel, for example, has supported this since 2016.
# See:
# + https://reproducible-builds.org/docs/source-date-epoch/
# + https://github.com/pypa/wheel/blob/1b879e53fed1f179897ed47e55a68bc51df188db/wheel/archive.py#L36-L39
REPRODUCIBLE_BUILDS_ENV = dict(
    PYTHONHASHSEED="0", SOURCE_DATE_EPOCH=str(DETERMINISTIC_DATETIME_TIMESTAMP)
)


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
    if len(noun) == 1:
        raise ValueError("There is no single letter noun; given: {noun}".format(noun=noun))
    if noun[-1] == "y" and noun[-2] not in ("a", "e", "i", "o", "u"):
        return noun[:-1] + "ies"
    elif noun[-1] in ("s", "x", "z") or noun[-2:] in ("sh", "ch"):
        return noun + "es"
    else:
        return noun + "s"


def _process_diagnostic():
    # type: () -> str
    return (
        "login: {user} uid: {uid} gid: {gid}\n"
        "effective: uid: {euid} gid: {egid}\n"
        "groups: {groups}"
    ).format(
        user=os.getlogin(),
        uid=os.getuid(),
        euid=os.geteuid(),
        gid=os.getgid(),
        egid=os.getegid(),
        groups=os.getgroups(),
    )


def _path_diagnostic(path):
    # type: (Text) -> Text

    path_type = "<unknown path type>"
    if os.path.isdir(path):
        path_type = "dir"
    elif os.path.isfile(path):
        path_type = "file"

    try:
        os_stat = os.stat(path)

        mode = oct(os_stat.st_mode)
        if hasattr(stat, "filemode"):
            mode = "{mode} ({human_mode})".format(
                mode=mode, human_mode=stat.filemode(os_stat.st_mode)  # type: ignore[attr-defined]
            )

        return (
            "{path_type} ok? {path!r}:\n"
            "    mode: {mode} owner: {uid} group: {gid}\n"
            "    {stat}".format(
                path_type=path_type,
                path=path,
                mode=mode,
                uid=os_stat.st_uid,
                gid=os_stat.st_gid,
                stat=os_stat,
            )
        )
    except OSError as e:
        return "{path_type} err {path!r}:\n    {err}".format(path_type=path_type, path=path, err=e)


def safe_copy(source, dest, overwrite=False):
    # type: (Text, Text, bool) -> None
    def do_copy():
        # type: () -> None
        temp_dest = dest + uuid4().hex
        shutil.copy(source, temp_dest)
        safe_rename(temp_dest, dest)

    # If the platform supports hard-linking, use that and fall back to copying.
    # Windows does not support hard-linking.
    if hasattr(os, "link"):
        try:
            safe_link(source, dest)
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
                raise OSError(
                    e.errno,
                    "Failed to link {src} -> {dst}: {strerror}\n"
                    "{process_diagnostic}\n"
                    "{src_diagnostic}\n"
                    "{dst_diagnostic}".format(
                        src=source,
                        dst=dest,
                        strerror=e.strerror,
                        process_diagnostic=_process_diagnostic(),
                        src_diagnostic=_path_diagnostic(source),
                        dst_diagnostic=_path_diagnostic(os.path.dirname(dest)),
                    ),
                )
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


def _reraise_walk_error(error):
    # type: (OSError) -> None
    raise error


# The position of os.walk's `onerror` parameter, so an explicit positional argument can be
# detected: os.walk(top, topdown=True, onerror=None, followlinks=False).
_ONERROR_POSITION = 2


def deterministic_walk(*args, **kwargs):
    # type: (*Any, **Any) -> Iterator[Tuple[str, List[str], List[str]]]
    """Walk the specified directory tree in deterministic order.

    Takes the same parameters as os.walk and yields tuples of the same shape, except that
    `topdown` must always be true -- os.walk ignores modifications to `dirs` when it is false --
    and `onerror` defaults to re-raising instead of os.walk's silent discard. Pass `onerror`
    explicitly, including `None`, to choose other handling.

    os.walk uses os.listdir or os.scandir, depending on the Python version, neither of which
    guarantees the order in which directory entries get listed. So when the build output depends
    on the order of directory traversal, use deterministic_walk instead.

    The `onerror` default matters to callers that walk a tree in order to reproduce it elsewhere.
    Under `onerror=None` a directory that cannot be listed is dropped along with everything below
    it, the walk still completes normally, and the caller writes out a truncated copy that every
    downstream consumer treats as whole. Raising surfaces the errno at the point of loss.

    That covers listing errors only. os.walk stays silent about two further losses:

    + An entry that cannot be stat-ed is classified as a file and never descended into, with no
      call to `onerror`. A stat is needed for symlinks and, on filesystems whose directory
      listings omit the entry type -- NFS, overlayfs and many FUSE filesystems among them -- for
      every entry.
    + An error part way through listing a directory discards the entries already read from it, so
      that directory is omitted as well, not just the part after the error.
    """
    # when topdown is false, modifying ``dirs`` has no effect
    assert kwargs.get("topdown", True), "Determinism cannot be guaranteed when ``topdown`` is false"
    if len(args) <= _ONERROR_POSITION and "onerror" not in kwargs:
        kwargs["onerror"] = _reraise_walk_error
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
    # type: (_Text, bool) -> _Text
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
    # type: (_Text) -> None
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


def touch(
    file,  # type: _Text
    times=None,  # type: Optional[Union[int, float, Tuple[int, int], Tuple[float, float]]]
):
    # type: (...) -> _Text
    """Equivalent of unix `touch path`.

    If no times is passed, the current time is used to set atime and mtime. If a single int or float
    is passed for times, it is used for both atime and mtime. If a 2-tuple of ints or floats is
    passed, the 1st slot is the atime and the 2nd the mtime, just as for `os.utime`.
    """
    with safe_open(file, "a"):
        os.utime(file, (times, times) if isinstance(times, (int, float)) else times)
    return file


def safe_relative_symlink(
    src,  # type: Text
    dst,  # type: Text
):
    # type: (...) -> None
    """Creates a symlink to `src` at `dst` using the relative path to `src` from `dst`.

    :param src: The target of the symlink.
    :param dst: The path to create the symlink at.
    """
    dst_parent = os.path.dirname(dst)
    safe_mkdir(dst_parent)
    rel_src = os.path.relpath(src, dst_parent)
    safe_symlink(rel_src, dst)


class CopyMode(Enum["CopyMode.Value"]):
    class Value(Enum.Value):
        pass

    COPY = Value("copy")
    LINK = Value("link")
    SYMLINK = Value("symlink")


CopyMode.seal()


def iter_copytree(
    src,  # type: Text
    dst,  # type: Text
    exclude=(),  # type: Container[Text]
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
):
    # type: (...) -> Iterator[Tuple[Text, Text]]
    """Copies the directory tree rooted at `src` to `dst` yielding a tuple for each copied file.

    When not using symlinks, if hard links are appropriate they will be used; otherwise files are
    copied.

    N.B.: The returned iterator must be consumed to drive the copying operations to completion.

    :param src: The source directory tree to copy.
    :param dst: The destination location to copy the source tree to.
    :param exclude: Names (basenames) of files and directories to exclude from copying.
    :param copy_mode: How to copy files.
    :return: An iterator over tuples identifying the copied files of the form `(src, dst)`.
    """
    safe_mkdir(dst)
    link = copy_mode is CopyMode.LINK
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
                if copy_mode is CopyMode.SYMLINK:
                    safe_relative_symlink(src_entry, dst_entry)
                elif is_dir:
                    os.mkdir(dst_entry)
                else:
                    # We only try to link regular files since linking a symlink on Linux can produce
                    # another symlink, which leaves open the possibility the src_entry target could
                    # later go missing leaving the dst_entry dangling.
                    if link and not os.path.islink(src_entry):
                        try:
                            safe_link(src_entry, dst_entry)
                            continue
                        except OSError as e:
                            if e.errno != errno.EXDEV:
                                raise e
                            link = False
                    shutil.copy(src_entry, dst_entry)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise e

        if copy_mode is CopyMode.SYMLINK:
            # Once we've symlinked the top-level directories and files, we've "copied" everything.
            return


@contextmanager
def environment_as(**kwargs):
    # type: (**Any) -> Iterator[None]
    """Mutates the `os.environ` for the duration of the context.

    Keyword arguments with None values are removed from os.environ (if present) and all other
    keyword arguments are added or updated in `os.environ` with the values taken from the
    stringification (`str(...)`) of each value.
    """
    existing = {key: os.environ.get(key) for key in kwargs}

    def adjust_environment(mapping):
        for key, value in mapping.items():
            if value is not None:
                os.environ[key] = str(value)
            else:
                os.environ.pop(key, None)

    adjust_environment(kwargs)
    try:
        yield
    finally:
        adjust_environment(existing)
