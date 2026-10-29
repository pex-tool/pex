# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import io
import os
import shutil
import stat
import sys
import time
import zipfile
from collections import namedtuple
from contextlib import closing
from zipfile import ZipFile, ZipInfo

from pex.common import DETERMINISTIC_DATETIME, safe_mkdir
from pex.enum import Enum
from pex.executables import chmod_plus_x
from pex.modes import Modes
from pex.os import is_exe
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Optional, Text, Tuple, Union

    from pex.hashing_types import Digest


# When Zip64 support was added to Python long ago, the limit was set to
# half of what it should be. Pex is always dealing with zips it creates
# via Python and so it does not need to worry about zip implemntations
# that don't support 4GB; so we monkeypatch our way out of this
# historical baggage to get working <= 4GB PEXes even on Python 2.7.
#
# See: https://github.com/python/cpython/issues/43003
setattr(zipfile, "ZIP64_LIMIT", (1 << 32) - 1)


class _ZipFileTypeValue(Enum.Value):
    def __init__(
        self,
        value,  # type: str
        deterministic_mode,  # type: int
    ):
        # type: (...) -> None
        super(_ZipFileTypeValue, self).__init__(value)
        self.deterministic_mode = deterministic_mode

    @property
    def deterministic_external_attr(self):
        # type: () -> int
        return self.deterministic_mode << 16


class ZipFileType(Enum["ZipFileType.Value"]):
    @classmethod
    def from_zip_info(cls, zip_info):
        # type: (ZipInfo) -> ZipFileType.Value

        if zip_info.filename.endswith("/"):
            return ZipFileType.DIRECTORY

        mode = zip_info.external_attr >> 16
        if stat.S_IXUSR & mode:
            return ZipFileType.EXECUTABLE

        return ZipFileType.FILE

    @classmethod
    def from_path(cls, path):
        # type: (Text) -> ZipFileType.Value
        if os.path.isdir(path):
            return ZipFileType.DIRECTORY
        elif is_exe(path):
            return ZipFileType.EXECUTABLE
        return ZipFileType.FILE

    class Value(_ZipFileTypeValue):
        pass

    DIRECTORY = Value("directory", stat.S_IFDIR | 0o755)
    EXECUTABLE = Value("executable", stat.S_IFREG | 0o755)
    FILE = Value("file", stat.S_IFREG | 0o644)


ZipFileType.seal()


class ZipFileEx(ZipFile):
    """A ZipFile that works around several issues in the stdlib.

    See:
    + https://bugs.python.org/issue15795
    + https://github.com/pex-tool/pex/issues/298
    """

    class ZipEntry(namedtuple("ZipEntry", ["info", "data"])):
        pass

    @classmethod
    def zip_info_from_file(
        cls,
        filename,  # type: Text
        arcname=None,  # type: Optional[Text]
        date_time=None,  # type: Optional[time.struct_time]
        file_mode=None,  # type: Optional[int]
        compress=True,  # type: bool
    ):
        # type: (...) -> Tuple[ZipInfo, bool]
        """Construct a ZipInfo for a file on the filesystem.

        Usually a similar `from_file` method is provided by `ZipInfo`, but it is not implemented in
         Python 2.7 or Python 3.5; so we re-implement it here adding the possibility to control the
         `ZipInfo` date_time separately from the underlying file mtime.
         See https://github.com/python/cpython/blob/9d3b53c47fab9ebf1f40d6f21b7d1ad391c14cd7/Lib/zipfile/__init__.py#L607-L642
        """
        st = os.stat(filename)
        is_dir = stat.S_ISDIR(st.st_mode)
        if arcname is None:
            arcname = filename
        arcname = os.path.normpath(os.path.splitdrive(arcname)[1])
        while arcname[0] in (os.sep, os.altsep):
            arcname = arcname[1:]
        if is_dir:
            arcname += "/"
        if date_time is None:
            date_time = time.localtime(st.st_mtime)
        zip_info = zipfile.ZipInfo(filename=arcname, date_time=date_time[:6])

        # Unix attributes
        zip_info.external_attr = ((file_mode or st.st_mode) & 0xFFFF) << 16

        if is_dir:
            zip_info.file_size = 0
            zip_info.external_attr |= 0x10  # MS-DOS directory flag
            zip_info.compress_type = zipfile.ZIP_STORED
        else:
            zip_info.file_size = st.st_size
            zip_info.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
        return zip_info, is_dir

    def __init__(self, *args, **kwargs):
        self._modes = kwargs.pop("modes", Modes())  # type: Optional[Modes]
        super(ZipFileEx, self).__init__(*args, **kwargs)

    def _file_mode(self, path):
        # type: (Text) -> int

        if self._modes is None:
            # I'm not sure why MyPy can figure this one out.
            return cast(int, os.stat(path).st_mode)

        zip_file_type = ZipFileType.from_path(path)
        if zip_file_type is ZipFileType.DIRECTORY:
            return self._modes.directory
        elif zip_file_type is ZipFileType.EXECUTABLE:
            return self._modes.executable
        else:
            return self._modes.file

    def write_deterministic(
        self,
        filename,  # type: Text
        arcname=None,  # type: Optional[Text]
        digest=None,  # type: Optional[Digest]
        deterministic=True,  # type: bool
        compress=True,  # type: bool
    ):
        if deterministic:
            return self.write_ex(
                filename,
                arcname=arcname,
                date_time=DETERMINISTIC_DATETIME.timetuple(),
                file_mode=self._file_mode(filename),
                digest=digest,
                compress=compress,
            )
        return self.write_ex(filename, arcname=arcname, digest=digest, compress=compress)

    def write_ex(
        self,
        filename,  # type: Text
        arcname=None,  # type: Optional[Text]
        date_time=None,  # type: Optional[time.struct_time]
        file_mode=None,  # type: Optional[int]
        digest=None,  # type: Optional[Digest]
        compress=True,  # type: bool
    ):
        # type: (...) -> int
        zip_info, is_dir = self.zip_info_from_file(
            filename, arcname=arcname, date_time=date_time, file_mode=file_mode, compress=compress
        )
        size = 0
        if is_dir:
            self.writestr(zip_info, b"")
        elif sys.version_info[:2] >= (3, 6):
            with closing(self.open(zip_info, "w")) as dst_fp, open(filename, "rb") as src_fp:
                for chunk in iter(lambda: src_fp.read(io.DEFAULT_BUFFER_SIZE), b""):
                    size += len(chunk)
                    if digest:
                        digest.update(chunk)
                    dst_fp.write(chunk)
        else:
            with open(filename, "rb") as fp:
                data = fp.read()
            size = len(data)
            if digest:
                digest.update(data)
            self.writestr(zip_info, data)
        return size

    def _extract_member(
        self,
        member,  # type: Union[str, ZipInfo]
        targetpath,  # type: str
        pwd,  # type: Optional[bytes]
    ):
        # type: (...) -> str

        # MyPy doesn't see the superclass private method.
        result = super(ZipFileEx, self)._extract_member(  # type: ignore[misc]
            member, targetpath, pwd
        )
        info = member if isinstance(member, zipfile.ZipInfo) else self.getinfo(member)
        self._chmod(info, result)
        return cast(str, result)

    @staticmethod
    def _chmod(
        info,  # type: ZipInfo
        path,  # type: Text
    ):
        # type: (...) -> None

        # This magic works to extract perm bits from the 32 bit external file attributes field for
        # unix-created zip files, for the layout, see:
        #   https://www.forensicswiki.org/wiki/ZIP#External_file_attributes
        if info.external_attr > 0xFFFF:
            attr = info.external_attr >> 16
            # If the archive file was executable, we set the extracted file as executable.
            if stat.S_ISREG(attr) and attr & 0o111:
                chmod_plus_x(path)

    # Python 3 also takes PathLike[str] for the path arg, but we only ever pass str since we support
    # Python 2.7 and don't use pathlib as a result.
    def extractall(  # type: ignore[override]
        self,
        path=None,  # type: Optional[str]
        members=None,  # type: Optional[Iterable[Union[str, ZipInfo]]]
        pwd=None,  # type: Optional[bytes]
    ):
        # type: (...) -> None
        if sys.version_info[0] != 2:
            return super(ZipFileEx, self).extractall(path=path, members=members, pwd=pwd)

        # Under Python 2.7, ZipFile does not handle Zip entry name encoding correctly. Older Zip
        # standards supported IBM code page 437 and newer support UTF-8. The newer support is
        # indicated by the bit 11 flag in the file header.
        # From https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT section
        # "4.4.4 general purpose bit flag: (2 bytes)":
        #
        #   Bit 11: Language encoding flag (EFS).  If this bit is set,
        #           the filename and comment fields for this file
        #           MUST be encoded using UTF-8. (see APPENDIX D)
        #
        # N.B.: MyPy fails to see this code can be reached for Python 2.7.
        efs_bit = 1 << 11  # type: ignore[unreachable]

        target_path = path or os.getcwd()
        for member in members or self.infolist():
            info = member if isinstance(member, ZipInfo) else self.getinfo(member)
            encoding = "utf-8" if info.flag_bits & efs_bit else "cp437"
            member_path = info.filename.encode(encoding)
            target = target_path.encode(encoding)

            rel_dir = os.path.dirname(member_path)
            abs_dir = os.path.join(target, rel_dir)
            abs_path = os.path.join(abs_dir, os.path.basename(member_path))
            if member_path.endswith(b"/"):
                safe_mkdir(abs_path)
            else:
                safe_mkdir(abs_dir)
                with open(abs_path, "wb") as tfp, self.open(info) as zf_entry:
                    shutil.copyfileobj(zf_entry, tfp)
            self._chmod(info, abs_path)


@contextlib.contextmanager
def open_zip(
    path,  # type: Text
    *args,  # type: Any
    **kwargs  # type: Any
):
    # type: (...) -> Iterator[ZipFileEx]
    """A contextmanager for zip files.

    Passes through positional and kwargs to zipfile.ZipFile.
    """

    # allowZip64=True is the default in Python 3.4+ but not in 2.7. We uniformly enable Zip64
    # extensions across all Pex supported Pythons.
    kwargs.setdefault("allowZip64", True)

    kwargs.setdefault("modes", Modes())
    with contextlib.closing(ZipFileEx(path, *args, **kwargs)) as zip_fp:
        yield zip_fp
