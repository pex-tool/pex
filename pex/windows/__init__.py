# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import os.path
import struct
import uuid
import zipfile
from typing import Iterator, Optional

from pex.common import safe_open
from pex.fetcher import URLFetcher
from pex.fs import safe_rename
from pex.os import Os
from pex.sysconfig import SysPlatform
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Text

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


def _fetch_stub(stub_name):
    # type: (str) -> bytes
    with URLFetcher().get_body_stream(
        "https://raw.githubusercontent.com/astral-sh/uv/refs/tags/{version}/crates/uv-trampoline/"
        "trampolines/{stub_name}".format(version=_TRAMPOLINE_VERSION, stub_name=stub_name)
    ) as in_fp:
        return in_fp.read()


@attr.s(frozen=True)
class Stub(object):
    path = attr.ib()  # type: str
    data = attr.ib()  # type: bytes


def _load_stub(
    platform=SysPlatform.CURRENT,  # type: SysPlatform.Value
    gui=False,  # type: bool
):
    # type: (...) -> Stub

    stub_name = _stub_name(platform=platform, gui=gui)
    stub_dst = os.path.join(os.path.dirname(__file__), "stubs", stub_name)
    if os.path.exists(stub_dst):
        with open(stub_dst, "rb") as fp:
            return Stub(path=stub_dst, data=fp.read())

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


def create_script(
    path,  # type: Text
    contents,  # type: Text
    platform=SysPlatform.CURRENT,  # type: SysPlatform.Value
    gui=False,  # type: bool
    python_path=None,  # type: Optional[Text]
):
    # type: (...) -> None

    with open("{path}.{unique}".format(path=path, unique=uuid.uuid4().hex), "wb") as fp:
        fp.write(_load_stub(platform=platform, gui=gui).data)
        with contextlib.closing(zipfile.ZipFile(fp, "a")) as zip_fp:
            zip_fp.writestr("__main__.py", contents.encode("utf-8"), zipfile.ZIP_STORED)
        python_path_bytes = platform.binary_name(
            python_path or ("pythonw" if gui else "python")
        ).encode("utf-8")
        fp.write(python_path_bytes)
        fp.write(struct.pack("<I", len(python_path_bytes)))
        fp.write(b"UVSC")
    safe_rename(fp.name, platform.binary_name(path))
