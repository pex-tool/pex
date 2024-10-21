# Copyright 2022 Pex project contributors.
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
from testing import PY_VER

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
            "Please file an issue at https://github.com/pex-tool/pex/issues/new that includes "
            "this full backtrace if you need this support.".format(path=zip_file, eol=os.linesep)
        ),
    ):
        Zip.load(zip_file)


def assert_zipapp(
    path,  # type: str
    expected_comment=b"",  # type: bytes
):
    # type: (...) -> None

    with open_zip(path) as zip_fp:
        assert ["__main__.py", "data.py", "data"] == zip_fp.namelist()
        assert expected_comment == zip_fp.comment

    # Older Pythons cannot execute zipapps with comments. The C runtime has a separate zip
    # implementation from the zipfile module, and it chokes.
    # See the fix here in 3.8.0 alpha1: https://github.com/python/cpython/issues/50200
    if not expected_comment or PY_VER >= (3, 8):
        assert b"42" == subprocess.check_output(args=[sys.executable, path]).strip()


def create_zipapp(
    tmpdir,  # type: Any
    comment=b"",  # type: bytes
):
    # type: (...) -> str

    zip_file = os.path.join(str(tmpdir), "zip_file")
    with open_zip(zip_file, "w") as zip_fp:
        zip_fp.writestr("__main__.py", b"print('42')")
        zip_fp.writestr("data.py", b"import pkgutil; print(pkgutil.getdata(__name__, 'data'))")
        zip_fp.writestr("data", b"42")
        zip_fp.comment = comment
    assert_zipapp(zip_file, expected_comment=comment)
    return zip_file


@pytest.mark.parametrize(
    "header",
    [pytest.param(b"", id="no header"), pytest.param(b"One line.\nAnother.\nTrailer", id="header")],
)
@pytest.mark.parametrize(
    "comment",
    [pytest.param(b"", id="no comment"), pytest.param(b"Phil Katz was here.", id="comment")],
)
def test_header_isolation(
    tmpdir,  # type: Any
    header,  # type: bytes
    comment,  # type: bytes
):
    # type: (...) -> None

    zip_file = create_zipapp(tmpdir, comment=comment)

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
    assert_zipapp(out_zip, expected_comment=comment)


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
