# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import base64
import csv
import errno
import hashlib
import itertools
import json
import os
import shutil
from fileinput import FileInput

from pex import hashing
from pex.common import CopyMode, is_pyc_dir, is_pyc_file, safe_mkdir, safe_open
from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper
from pex.venv.virtualenv import Virtualenv
from pex.wheel import WHEEL, Wheel, WheelMetadataLoadError

if TYPE_CHECKING:
    from typing import Callable, Iterable, Iterator, Optional, Protocol, Text, Tuple, Union

    import attr  # vendor:skip

    from pex.hashing import Hasher

    class CSVWriter(Protocol):
        def writerow(self, row):
            # type: (Iterable[Union[str, int]]) -> None
            pass

else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Digest(object):
    algorithm = attr.ib()  # type: str
    encoded_hash = attr.ib()  # type: str

    def new_hasher(self):
        # type: () -> Hasher
        return hashlib.new(self.algorithm)


@attr.s(frozen=True)
class Hash(object):
    @classmethod
    def create(cls, hasher):
        # type: (Hasher) -> Hash

        # The fingerprint encoding is defined for PEP-376 RECORD files as `urlsafe-base64-nopad`
        # which is fully spelled out in code in PEP-427:
        # + https://peps.python.org/pep-0376/#record
        # + https://peps.python.org/pep-0427/#appendix
        fingerprint = base64.urlsafe_b64encode(hasher.digest()).rstrip(b"=")
        return cls(value="{alg}={hash}".format(alg=hasher.name, hash=fingerprint.decode("ascii")))

    value = attr.ib()  # type: str

    def __str__(self):
        # type: () -> str
        return self.value


def find_and_replace_path_components(
    path,  # type: Text
    find,  # type: str
    replace,  # type: str
):
    # type: (...) -> Text
    """Replace components of `path` that are exactly `find` with `replace`.

    >>> find_and_replace_path_components("foo/bar/baz", "bar", "spam")
    foo/spam/baz
    >>>
    """
    if not find or not replace:
        raise ValueError(
            "Both find and replace must be non-empty strings. Given find={find!r} "
            "replace={replace!r}".format(find=find, replace=replace)
        )
    if not path:
        return path

    components = []
    head = path
    while head:
        new_head, tail = os.path.split(head)
        if new_head == head:
            components.append(head)
            break
        components.append(tail)
        head = new_head
    components.reverse()
    return os.path.join(*(replace if component == find else component for component in components))


@attr.s(frozen=True)
class InstalledFile(object):
    """The record of a single installed file from a PEP 376 RECORD file.

    See: https://www.python.org/dev/peps/pep-0376/#record
    """

    _PYTHON_VER_PLACEHOLDER = "pythonX.Y"

    @staticmethod
    def _python_ver(interpreter=None):
        # type: (Optional[PythonInterpreter]) -> str
        python = interpreter or PythonInterpreter.get()
        return "python{major}.{minor}".format(major=python.version[0], minor=python.version[1])

    @classmethod
    def normalized_path(
        cls,
        path,  # type: Text
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> Text
        return find_and_replace_path_components(
            path, cls._python_ver(interpreter=interpreter), cls._PYTHON_VER_PLACEHOLDER
        )

    @classmethod
    def denormalized_path(
        cls,
        path,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> Text
        return find_and_replace_path_components(
            path, cls._PYTHON_VER_PLACEHOLDER, cls._python_ver(interpreter=interpreter)
        )

    path = attr.ib()  # type: Text
    hash = attr.ib(default=None)  # type: Optional[Hash]
    size = attr.ib(default=None)  # type: Optional[int]


@attr.s(frozen=True)
class InstalledWheel(object):
    class LoadError(Exception):
        """Indicates an installed wheel was not loadable at a particular path."""

    _LAYOUT_JSON_FILENAME = ".layout.json"

    @classmethod
    def layout_file(cls, prefix_dir):
        # type: (str) -> str
        return os.path.join(prefix_dir, cls._LAYOUT_JSON_FILENAME)

    @classmethod
    def save(
        cls,
        prefix_dir,  # type: str
        stash_dir,  # type: str
        record_relpath,  # type: Text
        root_is_purelib,  # type: bool
    ):
        # type: (...) -> InstalledWheel

        # We currently need the installed wheel chroot hash for PEX-INFO / boot purposes. It is
        # expensive to calculate; so we do it here 1 time when saving the installed wheel.
        fingerprint = CacheHelper.dir_hash(prefix_dir, hasher=hashlib.sha256)

        layout = {
            "stash_dir": stash_dir,
            "record_relpath": record_relpath,
            "fingerprint": fingerprint,
            "root_is_purelib": root_is_purelib,
        }
        with open(cls.layout_file(prefix_dir), "w") as fp:
            json.dump(layout, fp, sort_keys=True)
        return cls(
            prefix_dir=prefix_dir,
            stash_dir=stash_dir,
            record_relpath=record_relpath,
            fingerprint=fingerprint,
            root_is_purelib=root_is_purelib,
        )

    @classmethod
    def load(cls, prefix_dir):
        # type: (str) -> InstalledWheel
        layout_file = cls.layout_file(prefix_dir)
        try:
            with open(layout_file) as fp:
                layout = json.load(fp)
        except (IOError, OSError) as e:
            raise cls.LoadError(
                "Failed to load an installed wheel layout from {layout_file}: {err}".format(
                    layout_file=layout_file, err=e
                )
            )
        if not isinstance(layout, dict):
            raise cls.LoadError(
                "The installed wheel layout file at {layout_file} must contain a single top-level "
                "object, found: {value}.".format(layout_file=layout_file, value=layout)
            )
        stash_dir = layout.get("stash_dir")
        record_relpath = layout.get("record_relpath")
        if not stash_dir or not record_relpath:
            raise cls.LoadError(
                "The installed wheel layout file at {layout_file} must contain an object with both "
                "`stash_dir` and `record_relpath` attributes, found: {value}".format(
                    layout_file=layout_file, value=layout
                )
            )

        fingerprint = layout.get("fingerprint")

        # N.B.: Caching root_is_purelib was not part of the original InstalledWheel layout data; so
        # we materialize the property if needed to support older installed wheel chroots.
        root_is_purelib = layout.get("root_is_purelib")
        if root_is_purelib is None:
            try:
                wheel = WHEEL.load(prefix_dir)
            except WheelMetadataLoadError as e:
                raise cls.LoadError(
                    "Failed to determine if installed wheel at {location} is platform-specific: "
                    "{err}".format(location=prefix_dir, err=e)
                )
            root_is_purelib = wheel.root_is_purelib

        return cls(
            prefix_dir=prefix_dir,
            stash_dir=cast(str, stash_dir),
            record_relpath=cast(str, record_relpath),
            fingerprint=cast("Optional[str]", fingerprint),
            root_is_purelib=root_is_purelib,
        )

    prefix_dir = attr.ib()  # type: str
    stash_dir = attr.ib()  # type: str
    record_relpath = attr.ib()  # type: Text
    fingerprint = attr.ib()  # type: Optional[str]
    root_is_purelib = attr.ib()  # type: bool

    def wheel_file_name(self):
        # type: () -> str
        return Wheel.load(self.prefix_dir).wheel_file_name

    def stashed_path(self, *components):
        # type: (*str) -> str
        return os.path.join(self.prefix_dir, self.stash_dir, *components)

    @staticmethod
    def create_installed_file(
        path,  # type: Text
        dest_dir,  # type: str
    ):
        # type: (...) -> InstalledFile
        hasher = hashlib.sha256()
        hashing.file_hash(path, digest=hasher)
        return InstalledFile(
            path=os.path.relpath(path, dest_dir),
            hash=Hash.create(hasher),
            size=os.stat(path).st_size,
        )

    def _create_record(
        self,
        dst,  # type: Text
        installed_files,  # type: Iterable[InstalledFile]
    ):
        # type: (...) -> None
        Record.write(
            dst=os.path.join(dst, self.record_relpath),
            installed_files=[
                # The RECORD entry should never include hash or size; so we replace any such entry
                # with an un-hashed and un-sized one.
                InstalledFile(self.record_relpath, hash=None, size=None)
                if installed_file.path == self.record_relpath
                else installed_file
                for installed_file in installed_files
            ],
        )

    def reinstall_flat(
        self,
        target_dir,  # type: str
        copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    ):
        # type: (...) -> Iterator[Tuple[Text, Text]]
        """Re-installs the installed wheel in a flat target directory.

        N.B.: A record of reinstalled files is returned in the form of an iterator that must be
        consumed to drive the installation to completion.

        If there is an error re-installing a file due to it already existing in the target
        directory, the error is suppressed, and it's expected that the caller detects this by
        comparing the record of installed files against those installed previously.

        :return: An iterator over src -> dst pairs.
        """
        installed_files = [InstalledFile(self.record_relpath)]
        for src, dst in itertools.chain(
            self._reinstall_stash(dest_dir=target_dir, link=copy_mode is not CopyMode.COPY),
            self._reinstall_site_packages(target_dir, copy_mode=copy_mode),
        ):
            installed_files.append(self.create_installed_file(path=dst, dest_dir=target_dir))
            yield src, dst

        self._create_record(target_dir, installed_files)

    def reinstall_venv(
        self,
        venv,  # type: Virtualenv
        copy_mode=CopyMode.LINK,  # type: CopyMode.Value
        rel_extra_path=None,  # type: Optional[str]
    ):
        # type: (...) -> Iterator[Tuple[Text, Text]]
        """Re-installs the installed wheel in a venv.

        N.B.: A record of reinstalled files is returned in the form of an iterator that must be
        consumed to drive the installation to completion.

        If there is an error re-installing a file due to it already existing in the destination
        venv, the error is suppressed, and it's expected that the caller detects this by comparing
        the record of installed files against those installed previously.

        :return: An iterator over src -> dst pairs.
        """

        site_packages_dir = venv.purelib if self.root_is_purelib else venv.platlib
        site_packages_dir = (
            os.path.join(site_packages_dir, rel_extra_path) if rel_extra_path else site_packages_dir
        )

        installed_files = [InstalledFile(self.record_relpath)]
        for src, dst in itertools.chain(
            self._reinstall_stash(
                dest_dir=venv.venv_dir,
                interpreter=venv.interpreter,
                link=copy_mode is not CopyMode.COPY,
            ),
            self._reinstall_site_packages(site_packages_dir, copy_mode=copy_mode),
        ):
            installed_files.append(self.create_installed_file(path=dst, dest_dir=site_packages_dir))
            yield src, dst

        self._create_record(site_packages_dir, installed_files)

    def _reinstall_stash(
        self,
        dest_dir,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
        link=True,  # type: bool
    ):
        # type: (...) -> Iterator[Tuple[Text, Text]]

        stash_abs_path = os.path.join(self.prefix_dir, self.stash_dir)
        for root, dirs, files in os.walk(stash_abs_path, topdown=True, followlinks=True):
            dir_created = False
            for f in files:
                src = os.path.join(root, f)
                src_relpath = os.path.relpath(src, stash_abs_path)
                dst = InstalledFile.denormalized_path(
                    path=os.path.join(dest_dir, src_relpath), interpreter=interpreter
                )
                if not dir_created:
                    safe_mkdir(os.path.dirname(dst))
                    dir_created = True
                try:
                    # We only try to link regular files since linking a symlink on Linux can produce
                    # another symlink, which leaves open the possibility the src target could later
                    # go missing leaving the dst dangling.
                    if link and not os.path.islink(src):
                        try:
                            os.link(src, dst)
                            continue
                        except OSError as e:
                            if e.errno != errno.EXDEV:
                                raise e
                            link = False
                    shutil.copy(src, dst)
                except (IOError, OSError) as e:
                    if e.errno != errno.EEXIST:
                        raise e
                finally:
                    yield src, dst

    def _reinstall_site_packages(
        self,
        site_packages_dir,  # type: str
        copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    ):
        # type: (...) -> Iterator[Tuple[Text, Text]]

        link = copy_mode is CopyMode.LINK
        for root, dirs, files in os.walk(self.prefix_dir, topdown=True, followlinks=True):
            if root == self.prefix_dir:
                dirs[:] = [d for d in dirs if not is_pyc_dir(d) and d != self.stash_dir]
                files[:] = [
                    f for f in files if not is_pyc_file(f) and f != self._LAYOUT_JSON_FILENAME
                ]

            traverse = set(dirs)
            for path, is_dir in itertools.chain(
                zip(dirs, itertools.repeat(True)), zip(files, itertools.repeat(False))
            ):
                src_entry = os.path.join(root, path)
                dst_entry = os.path.join(
                    site_packages_dir, os.path.relpath(src_entry, self.prefix_dir)
                )
                try:
                    if copy_mode is CopyMode.SYMLINK and not (
                        src_entry.endswith(".dist-info") and os.path.isdir(src_entry)
                    ):
                        dst_parent = os.path.dirname(dst_entry)
                        safe_mkdir(dst_parent)
                        rel_src = os.path.relpath(src_entry, dst_parent)
                        os.symlink(rel_src, dst_entry)
                        traverse.discard(path)
                    elif is_dir:
                        safe_mkdir(dst_entry)
                    else:
                        # We only try to link regular files since linking a symlink on Linux can
                        # produce another symlink, which leaves open the possibility the src_entry
                        # target could later go missing leaving the dst_entry dangling.
                        if link and not os.path.islink(src_entry):
                            try:
                                os.link(src_entry, dst_entry)
                                continue
                            except OSError as e:
                                if e.errno != errno.EXDEV:
                                    raise e
                                link = False
                        shutil.copy(src_entry, dst_entry)
                except (IOError, OSError) as e:
                    if e.errno != errno.EEXIST:
                        raise e
                finally:
                    if not is_dir:
                        yield src_entry, dst_entry

            dirs[:] = list(traverse)


class RecordError(Exception):
    pass


class RecordNotFoundError(RecordError):
    """Indicates a distribution's RECORD metadata could not be found."""


class UnrecognizedInstallationSchemeError(RecordError):
    """Indicates a distribution's RECORD was nested in an unrecognized installation scheme."""


@attr.s(frozen=True)
class DistInfoFile(object):
    path = attr.ib()  # type: Text
    content = attr.ib()  # type: bytes


@attr.s(frozen=True)
class Record(object):
    """Represents the PEP-376 RECORD of an installed wheel.

    See: https://www.python.org/dev/peps/pep-0376/#record
    """

    @classmethod
    def write(
        cls,
        dst,  # type: Text
        installed_files,  # type: Iterable[InstalledFile]
    ):
        # type: (...) -> None

        # The RECORD is a csv file with the path to each installed file in the 1st column.
        # See: https://www.python.org/dev/peps/pep-0376/#record
        with safe_open(dst, "w") as fp:
            csv_writer = cast(
                "CSVWriter",
                csv.writer(fp, delimiter=",", quotechar='"', lineterminator="\n"),
            )
            for installed_file in sorted(installed_files, key=lambda installed: installed.path):
                csv_writer.writerow(attr.astuple(installed_file, recurse=False))

    @classmethod
    def read(
        cls,
        lines,  # type: Union[FileInput[Text], Iterator[Text]]
        exclude=None,  # type: Optional[Callable[[Text], bool]]
    ):
        # type: (...) -> Iterator[InstalledFile]

        # The RECORD is a csv file with the path to each installed file in the 1st column.
        # See: https://www.python.org/dev/peps/pep-0376/#record
        for line, (path, fingerprint, file_size) in enumerate(
            csv.reader(lines, delimiter=",", quotechar='"'), start=1
        ):
            resolved_path = path
            if exclude and exclude(resolved_path):
                continue
            file_hash = Hash(fingerprint) if fingerprint else None
            size = int(file_size) if file_size else None
            yield InstalledFile(path=path, hash=file_hash, size=size)

    project_name = attr.ib()  # type: str
    version = attr.ib()  # type: str
    prefix_dir = attr.ib()  # type: str
    rel_base_dir = attr.ib()  # type: Text
    relative_path = attr.ib()  # type: Text
