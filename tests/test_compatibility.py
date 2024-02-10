# Copyright 2015 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.compatibility import PY3, commonpath, indent, to_bytes, to_unicode

unicode_string = (str,) if PY3 else (unicode,)  # type: ignore[name-defined]


def test_to_bytes():
    # type: () -> None
    assert isinstance(to_bytes(""), bytes)
    assert isinstance(to_bytes("abc"), bytes)
    assert isinstance(to_bytes(b"abc"), bytes)
    assert isinstance(to_bytes(u"abc"), bytes)
    assert isinstance(to_bytes(b"abc".decode("latin-1"), encoding=u"utf-8"), bytes)

    for bad_value in (123, None):
        with pytest.raises(ValueError):
            to_bytes(bad_value)  # type: ignore[type-var]


def test_to_unicode():
    # type: () -> None
    assert isinstance(to_unicode(""), unicode_string)
    assert isinstance(to_unicode("abc"), unicode_string)
    assert isinstance(to_unicode(b"abc"), unicode_string)
    assert isinstance(to_unicode(u"abc"), unicode_string)
    assert isinstance(to_unicode(u"abc".encode("latin-1"), encoding=u"latin-1"), unicode_string)

    for bad_value in (123, None):
        with pytest.raises(ValueError):
            to_unicode(bad_value)  # type: ignore[type-var]


def test_indent():
    # type: () -> None
    assert "  line1" == indent("line1", "  ")

    assert "  line1\n  line2" == indent("line1\nline2", "  ")
    assert "  line1\n  line2\n" == indent("line1\nline2\n", "  ")

    assert "  line1\n\n  line3" == indent("line1\n\nline3", "  ")
    assert "  line1\n \n  line3" == indent("line1\n \nline3", "  ")
    assert "  line1\n  \n  line3" == indent("line1\n\nline3", "  ", lambda line: True)


def test_commonpath_invalid():
    # type: () -> None

    with pytest.raises(ValueError):
        commonpath([])

    with pytest.raises(ValueError):
        commonpath(["a", "/a"])


def test_commonpath_single():
    # type: () -> None

    assert "" == commonpath([""])
    assert "/" == commonpath(["/"])
    assert "a" == commonpath(["a"])
    assert "/a" == commonpath(["/a"])


def test_commonpath_common():
    # type: () -> None

    assert "a" == commonpath(["a", "a"])
    assert "a" == commonpath(["a", "a/"])
    assert "a" == commonpath(["a", "a/b"])
    assert "a" == commonpath(["a/", "a/b"])
    assert "a" == commonpath(["a/c", "a/b"])

    assert "/a" == commonpath(["/a", "/a"])
    assert "/a" == commonpath(["/a", "/a/"])
    assert "/a" == commonpath(["/a", "/a/b"])
    assert "/a" == commonpath(["/a/", "/a/b"])
    assert "/a" == commonpath(["/a/c", "/a/b"])

    assert "a" == commonpath(["./a", "./a"])
    assert "a" == commonpath(["./a", "./a/"])
    assert "a" == commonpath(["./a", "./a/b"])
    assert "a" == commonpath(["./a/", "./a/b"])
    assert "a" == commonpath(["./a/c", "./a/b"])

    assert "../a" == commonpath(["../a", "../a"])
    assert "../a" == commonpath(["../a", "../a/"])
    assert "../a" == commonpath(["../a", "../a/b"])
    assert "../a" == commonpath(["../a/", "../a/b"])
    assert "../a" == commonpath(["../a/c", "../a/b"])

    assert "a/b" == commonpath(["./a/./b", "./a/b"])
    assert "a/../b" == commonpath(["./a/.././b", "a/../b/c"])


def test_commonpath_none():
    # type: () -> None

    assert "" == commonpath(["a", "b"])
    assert "" == commonpath(["bad", "b"])
    assert "" == commonpath(["a", "a", "b"])
