# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import os.path
import shutil
import struct
import uuid
import zipfile

from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir
from pex.common import open_zip, safe_open
from pex.executables import chmod_plus_x
from pex.fetcher import URLFetcher
from pex.fs import safe_rename
from pex.os import Os
from pex.sysconfig import SysPlatform
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Optional, Text, TypeVar

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _stub_name(
    platform=SysPlatform.CURRENT,  # type: SysPlatform.Value
    gui=False,  # type: bool
):
    # type: (...) -> str

    if platform.os is not Os.WINDOWS:
        raise ValueError(
            "Script stubs are only available for Windows platforms; given: {platform}".format(
                platform=platform
            )
        )

    return platform.binary_name(
        "uv-trampoline-{arch}-{type}".format(arch=platform.arch, type="gui" if gui else "console")
    )


_TRAMPOLINE_VERSION = "0.5.29"
_EXTRA_HEADERS = (
    {
        "Authorization": "Bearer {bearer}".format(
            bearer=os.environ["_PEX_FETCH_WINDOWS_STUBS_BEARER"]
        )
    }
    if "_PEX_FETCH_WINDOWS_STUBS_BEARER" in os.environ
    else None
)
_CACHE_DIR = os.environ.get(
    "_PEX_CACHE_WINDOWS_STUBS_DIR", CacheDir.DEV.path("windows_stubs", _TRAMPOLINE_VERSION)
)


def _fetch_stub(stub_name):
    # type: (str) -> bytes

    stub_dir = os.path.join(_CACHE_DIR, stub_name)
    with atomic_directory(stub_dir) as atomic_dir:
        if not atomic_dir.is_finalized():
            with URLFetcher().get_body_stream(
                "https://raw.githubusercontent.com/astral-sh/uv/refs/tags/{version}/crates/"
                "uv-trampoline/trampolines/{stub_name}".format(
                    version=_TRAMPOLINE_VERSION, stub_name=stub_name
                ),
                extra_headers=_EXTRA_HEADERS,
            ) as in_fp, open(os.path.join(atomic_dir.work_dir, "stub.exe"), "wb") as out_fp:
                shutil.copyfileobj(in_fp, out_fp)
            chmod_plus_x(out_fp.name)

    with open(os.path.join(stub_dir, "stub.exe"), "rb") as in_fp:
        return in_fp.read()


@attr.s(frozen=True)
class Stub(object):
    path = attr.ib()  # type: str
    _data = attr.ib(default=None, eq=False)  # type: Optional[bytes]
    cached = attr.ib(init=False)  # type: bool

    def __attrs_post_init__(self):
        # type: () -> None
        object.__setattr__(self, "cached", self._data is None)

    def read_data(self):
        # type: () -> bytes
        if self._data is not None:
            return self._data
        with open(self.path, "rb") as fp:
            data = fp.read()
            object.__setattr__(self, "_data", data)
            return data


def _load_stub(
    platform=SysPlatform.CURRENT,  # type: SysPlatform.Value
    gui=False,  # type: bool
):
    # type: (...) -> Stub

    stub_name = _stub_name(platform=platform, gui=gui)
    stub_dst = os.path.join(os.path.dirname(__file__), "stubs", stub_name)
    if os.path.exists(stub_dst):
        return Stub(path=stub_dst)

    stub = _fetch_stub(stub_name)
    with safe_open(
        "{stub_dst}.{unique}".format(stub_dst=stub_dst, unique=uuid.uuid4().hex), "wb"
    ) as out_fp:
        out_fp.write(stub)
    safe_rename(out_fp.name, stub_dst)
    return Stub(path=stub_dst, data=stub)


def fetch_all_stubs():
    # type: () -> Iterator[Stub]
    for platform in (SysPlatform.WINDOWS_AARCH64, SysPlatform.WINDOWS_X86_64):
        for gui in (True, False):
            yield _load_stub(platform=platform, gui=gui)


if TYPE_CHECKING:
    _Text = TypeVar("_Text", str, Text)


def create_script(
    path,  # type: _Text
    contents,  # type: Text
    platform=SysPlatform.CURRENT,  # type: SysPlatform.Value
    gui=False,  # type: bool
    python_path=None,  # type: Optional[Text]
):
    # type: (...) -> _Text

    with safe_open("{path}.{unique}".format(path=path, unique=uuid.uuid4().hex), "wb") as fp:
        fp.write(_load_stub(platform=platform, gui=gui).read_data())
        with contextlib.closing(zipfile.ZipFile(fp, "a")) as zip_fp:
            zip_fp.writestr("__main__.py", contents.encode("utf-8"), zipfile.ZIP_STORED)
        python_path_bytes = platform.binary_name(
            python_path or ("pythonw" if gui else "python")
        ).encode("utf-8")
        fp.write(python_path_bytes)
        fp.write(struct.pack("<I", len(python_path_bytes)))
        fp.write(b"UVSC")
    script = platform.binary_name(path)
    safe_rename(fp.name, script)
    return script


def is_script(path):
    # type: (Text) -> bool

    if not zipfile.is_zipfile(path):
        return False
    with open(path, "rb") as fp:
        fp.seek(-4, os.SEEK_END)
        if b"UVSC" != fp.read():
            return False
    with open_zip(path) as zip_fp:
        return "__main__.py" in zip_fp.namelist()
