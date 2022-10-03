# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import filecmp
import os.path
import re
import shutil
import subprocess
import sys
from io import BytesIO

import pytest

from pex.common import open_zip
from pex.typing import TYPE_CHECKING
from pex.ziputils import Zip, ZipError

if TYPE_CHECKING:
    from typing import Any


def test_zip64_fail_fast(tmpdir):
    zip_file = os.path.join(str(tmpdir), "zip_file")
    with open_zip(zip_file, "w") as zip_fp:
        for x in range(100000):
            zip_fp.writestr("{x}.txt".format(x=x), bytes(x))

    with pytest.raises(
        ZipError,
        match=re.escape(
            "The zip at {path} requires Zip64 support.{eol}"
            "The disk_cd_record_count field of the EndOfCentralDirectoryRecord record has value "
            "65535 indicating Zip64 support is required, but Zip64 support is not implemented.{eol}"
            "Please file an issue at https://github.com/pantsbuild/pex/issues/new that includes "
            "this full backtrace if you need this support.".format(path=zip_file, eol=os.linesep)
        ),
    ):
        Zip.load(zip_file)


def assert_zipapp(path):
    # type: (str) -> None

    with open_zip(path) as zip_fp:
        assert ["__main__.py", "data.py", "data"] == zip_fp.namelist()
    assert b"42" == subprocess.check_output(args=[sys.executable, path]).strip()


def create_zipapp(tmpdir):
    # type: (Any) -> str

    zip_file = os.path.join(str(tmpdir), "zip_file")
    with open_zip(zip_file, "w") as zip_fp:
        zip_fp.writestr("__main__.py", b"print('42')")
        zip_fp.writestr("data.py", b"import pkgutil; print(pkgutil.getdata(__name__, 'data'))")
        zip_fp.writestr("data", b"42")
    assert_zipapp(zip_file)
    return zip_file


@pytest.mark.parametrize(
    "header",
    [pytest.param(b"", id="no header"), pytest.param(b"One line.\nAnother.\nTrailer", id="header")],
)
def test_header_isolation(
    tmpdir,  # type: Any
    header,  # type: bytes
):
    # type: (...) -> None

    zip_file = create_zipapp(tmpdir)

    zip_file_with_header = os.path.join(str(tmpdir), "zip_file_with_header")
    with open(zip_file, "rb") as in_fp, open(zip_file_with_header, "wb") as out_fp:
        out_fp.write(header)
        shutil.copyfileobj(in_fp, out_fp)

    zf = Zip.load(zip_file_with_header)
    assert bool(header) == zf.has_header

    with BytesIO() as out_fp:
        assert b"" == zf.isolate_header(out_fp)
        assert header == out_fp.getvalue()

    out_zip = os.path.join(str(tmpdir), "out.zip")
    with open(out_zip, "wb") as out_fp:
        zf.isolate_zip(out_fp)

    assert filecmp.cmp(zip_file, out_zip, shallow=False)
    assert_zipapp(out_zip)


def test_sandwich(tmpdir):
    # type: (Any) -> None

    zip_file = create_zipapp(tmpdir)

    zip_file_with_header = os.path.join(str(tmpdir), "zip_file_with_header")
    with open(zip_file, "rb") as in_fp, open(zip_file_with_header, "wb") as out_fp:
        out_fp.write(b"A line.\nAnother.\n#!trailer shebang\n")
        shutil.copyfileobj(in_fp, out_fp)

    zf = Zip.load(zip_file_with_header)
    assert zf.has_header

    with BytesIO() as out_fp:
        assert b"#!trailer shebang\n" == zf.isolate_header(out_fp, stop_at=b"#!")
        assert b"A line.\nAnother.\n" == out_fp.getvalue()

    out_zip = os.path.join(str(tmpdir), "out.zip")
    with open(out_zip, "wb") as out_fp:
        zf.isolate_zip(out_fp)

    assert filecmp.cmp(zip_file, out_zip, shallow=False)
    assert_zipapp(out_zip)
