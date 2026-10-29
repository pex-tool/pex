# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
from collections import defaultdict
from zipfile import ZipInfo

from pex.enum import Enum
from pex.typing import TYPE_CHECKING
from pex.zipfile import open_zip

if TYPE_CHECKING:
    from typing import Any, DefaultDict, Dict, Set


def _ignore_compressed_size(info):
    # type: (ZipInfo) -> Dict[str, Any]

    normalized_info = {
        "CRC": info.CRC,
        "comment": info.comment,
        "compress_size": info.compress_size,
        "compress_type": info.compress_type,
        "create_system": info.create_system,
        "create_version": info.create_version,
        "date_time": info.date_time,
        "external_attr": info.external_attr,
        "extra": info.extra,
        "extract_version": info.extract_version,
        "file_size": info.file_size,
        "filename": info.filename,
        "flag_bits": info.flag_bits,
        "header_offset": info.header_offset,
        "internal_attr": info.internal_attr,
        "reserved": info.reserved,
        "volume": info.volume,
    }
    if hasattr(info, "compress_level"):
        normalized_info["compress_level"] = getattr(info, "compress_level")
    if hasattr(info, "orig_filename"):
        normalized_info["orig_filename"] = getattr(info, "orig_filename")

    normalized_info.pop("compress_size")
    # Varying compressed size also affects offsets in the zip; so we ignore those too.
    normalized_info.pop("header_offset")
    return normalized_info


def assert_equal_zips(
    zip1,  # type: str
    zip2,  # type: str
    ignore_compressed_size=True,
):
    # type: (...) -> None

    if ignore_compressed_size:
        with open_zip(zip1) as zf1, open_zip(zip2) as zf2:
            assert list(map(_ignore_compressed_size, zf1.infolist())) == list(
                map(_ignore_compressed_size, zf2.infolist())
            )
    else:
        assert filecmp.cmp(zip1, zip2, shallow=False)


class EntryType(Enum["EntryType.Value"]):
    class Value(Enum.Value):
        pass

    DIR = Value("dir")
    FILE = Value("file")


EntryType.seal()


def inventory_zip_modes(path):
    # type: (str) -> Dict[EntryType.Value, Set[int]]
    with open_zip(path) as zip_fp:
        inventory = defaultdict(set)  # type: DefaultDict[EntryType.Value, Set[int]]
        for zip_info in zip_fp.infolist():
            inventory[EntryType.DIR if zip_info.filename.endswith("/") else EntryType.FILE].add(
                zip_info.external_attr >> 16
            )
        return inventory
