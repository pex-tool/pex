# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import io
import os
import shutil
import struct

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class ZipError(Exception):
    """Indicates a problem reading a zip file."""


@attr.s(frozen=True)
class _Zip64Error(ZipError):
    """Indicates Zip64 support is required but not implemented."""

    record_type = attr.ib()  # type: str
    field = attr.ib()  # type: str
    value = attr.ib()  # type: int
    message = attr.ib(default="")  # type: str

    def __str__(self):
        # type: () -> str
        message_lines = [self.message] if self.message else []
        message_lines.append(
            "The {field} field of the {record_type} record has value {value} indicating Zip64 "
            "support is required, but Zip64 support is not implemented.".format(
                record_type=self.record_type,
                field=self.field,
                value=self.value,
            )
        )
        message_lines.append(
            "Please file an issue at https://github.com/pex-tool/pex/issues/new that includes "
            "this full backtrace if you need this support."
        )
        return os.linesep.join(message_lines)


_MAX_2_BYTES = 0xFFFF
_MAX_4_BYTES = 0xFFFFFFFF


@attr.s(frozen=True)
class _EndOfCentralDirectoryRecord(object):
    _SIGNATURE = b"\x50\x4b\x05\x06"
    _STRUCT = struct.Struct("<4sHHHHLLH")

    _MAX_SIZE = _STRUCT.size + (
        # The comment field is of variable length but that length is capped at a 2 byte integer.
        _MAX_2_BYTES
    )

    @classmethod
    def load(cls, zip_path):
        # type: (str) -> _EndOfCentralDirectoryRecord
        file_size = os.path.getsize(zip_path)
        if file_size < cls._STRUCT.size:
            raise ValueError(
                "The file at {path} is too small to be a valid Zip file.".format(path=zip_path)
            )

        with open(zip_path, "rb") as fp:
            # Try for the common case of no EOCD comment 1st.
            fp.seek(-cls._STRUCT.size, os.SEEK_END)
            if cls._SIGNATURE == fp.read(len(cls._SIGNATURE)):
                fp.seek(-len(cls._SIGNATURE), os.SEEK_CUR)
                return cls(cls._STRUCT.size, *cls._STRUCT.unpack(fp.read()))

            # There must be an EOCD comment, rewind to allow for the biggest possible comment (
            # which is not that big at all).
            read_size = min(cls._MAX_SIZE, file_size)
            fp.seek(-read_size, os.SEEK_END)
            last_data_chunk = fp.read()
            start_eocd = last_data_chunk.find(cls._SIGNATURE)
            _struct = cls._STRUCT.unpack_from(last_data_chunk, start_eocd)
            zip_comment = last_data_chunk[start_eocd + cls._STRUCT.size :]
            eocd_size = len(last_data_chunk) - start_eocd
            return cls(eocd_size, *(_struct + (zip_comment,)))

    size = attr.ib()  # type: int

    # See: https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT
    # 4.3.16  End of central directory record:
    #
    #       end of central dir signature    4 bytes  (0x06054b50)
    #       number of this disk             2 bytes
    #       number of the disk with the
    #       start of the central directory  2 bytes
    #       total number of entries in the
    #       central directory on this disk  2 bytes
    #       total number of entries in
    #       the central directory           2 bytes
    #       size of the central directory   4 bytes
    #       offset of start of central
    #       directory with respect to
    #       the starting disk number        4 bytes
    #       .ZIP file comment length        2 bytes
    #       .ZIP file comment       (variable size)

    sig = attr.ib()  # type: bytes
    disk_no = attr.ib(metadata={"max": _MAX_2_BYTES})  # type: int
    cd_disk_no = attr.ib(metadata={"max": _MAX_2_BYTES})  # type: int
    disk_cd_record_count = attr.ib(metadata={"max": _MAX_2_BYTES})  # type: int
    total_cd_record_count = attr.ib(metadata={"max": _MAX_2_BYTES})  # type: int
    cd_size = attr.ib(metadata={"max": _MAX_4_BYTES})  # type: int
    cd_offset = attr.ib(metadata={"max": _MAX_4_BYTES})  # type: int
    zip_comment_size = attr.ib()  # type: int
    zip_comment = attr.ib(default=b"")  # type: bytes

    @disk_no.validator
    @cd_disk_no.validator
    @disk_cd_record_count.validator
    @total_cd_record_count.validator
    @cd_size.validator
    @cd_offset.validator
    def _validate_does_not_require_zip64(
        self,
        attribute,  # type: attr.Attribute
        value,  # type: int
    ):
        # See: https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT
        #
        # 4.4.1.4  If one of the fields in the end of central directory
        #       record is too small to hold required data, the field SHOULD be
        #       set to -1 (0xFFFF or 0xFFFFFFFF) and the ZIP64 format record
        #       SHOULD be created.
        if value == attribute.metadata["max"]:
            raise _Zip64Error(
                record_type="EndOfCentralDirectoryRecord", field=attribute.name, value=value
            )

    @property
    def start_of_zip_offset_from_eof(self):
        # type: () -> int
        return self.size + self.cd_size + self.cd_offset


@attr.s(frozen=True)
class Zip(object):
    """Allows interacting with a Zip that may have arbitrary header content.

    Since the zip format is defined relative to the end of a file, a zip file can have arbitrary
    content pre-pended to it and not affect the validity of the zip archive. This class allows
    identifying if a Zip has arbitrary header content and then isolating that content from the zip
    archive.

    N.B.: Zips that need Zip64 extensions are not supported yet.
    """

    @classmethod
    def load(cls, path):
        # type: (str) -> Zip
        """Loads a zip file with detection of header presence.

        :raises: :class:`ZipError` if the zip could not be analyzed for the presence of a header.
        """
        try:
            eocd = _EndOfCentralDirectoryRecord.load(path)
        except _Zip64Error as e:
            raise attr.evolve(
                e, message="The zip at {path} requires Zip64 support.".format(path=path)
            )
        header_size = os.path.getsize(path) - eocd.start_of_zip_offset_from_eof
        return cls(path=path, header_size=header_size)

    path = attr.ib()  # type: str
    header_size = attr.ib()  # type: int

    @property
    def has_header(self):
        # type: () -> bool
        """Returns `True` if this zip has arbitrary header content."""
        return self.header_size > 0

    def isolate_header(
        self,
        out_fp,  # type: BinaryIO
        stop_at=None,  # type: Optional[bytes]
    ):
        # type: (...) -> bytes
        """Writes any non-zip header content to the given output stream.

        If `stop_at` is specified, all the header content up to the right-most (last) occurrence of
        the `stop_at` byte pattern is encountered. If the `stop_at` byte pattern is found, it and
        all the content after it and up until the start of the zip archive is returned.
        """

        if not self.has_header:
            return b""

        remaining = self.header_size
        with open(self.path, "rb") as in_fp:
            if stop_at:
                # Assume the `stop_at` pattern is closer to the end of the header content and search
                # backwards from there to be more efficient. This supports the pattern of
                # sandwiching "small" content between a head-based format (like Microsoft's PE
                # format, Apple's Mach-O format, ELF and even PNG) and a tail-based format like zip.
                #
                # In practice, Windows console scripts are implemented as a single file with a PE
                # loader executable head sandwiching a shebang line between it and a zip archive
                # trailer. The loader uses knowledge of its own format and the zip format to find
                # the sandwiched shebang line and then interpret it to find a suitable Python and
                # then execute that Python interpreter against the file which Python sees as a zip
                # with an embedded `__main__.py` entry point.
                in_fp.seek(self.header_size, os.SEEK_SET)
                while remaining > 0:
                    chunk_size = min(remaining, io.DEFAULT_BUFFER_SIZE)
                    in_fp.seek(-chunk_size, os.SEEK_CUR)
                    chunk = in_fp.read(chunk_size)
                    remaining -= len(chunk)

                    offset = chunk.rfind(stop_at)
                    if offset != -1:
                        remaining += offset
                        break

            excess = self.header_size - remaining
            in_fp.seek(0, os.SEEK_SET)
            for chunk in iter(lambda: in_fp.read(min(remaining, io.DEFAULT_BUFFER_SIZE)), b""):
                remaining -= len(chunk)
                out_fp.write(chunk)

            return in_fp.read(excess)

    def isolate_zip(self, out_fp):
        # type: (BinaryIO) -> None
        """Writes the pure zip archive portion of this zip file to the given output stream."""
        with open(self.path, "rb") as in_fp:
            if self.has_header:
                in_fp.seek(self.header_size, os.SEEK_SET)
            shutil.copyfileobj(in_fp, out_fp)
