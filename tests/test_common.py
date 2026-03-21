# Copyright 2016 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import errno
import os
import stat

import pytest

from pex.common import (
    Chroot,
    ZipFileEx,
    ZipFileType,
    deterministic_walk,
    open_zip,
    safe_mkdir,
    safe_open,
    temporary_dir,
    touch,
)
from pex.executables import chmod_plus_x
from pex.typing import TYPE_CHECKING
from testing import NonDeterministicWalk
from testing.pytest_utils.tmp import Tempdir

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]

if TYPE_CHECKING:
    from typing import Iterator, Tuple


def test_zip_file_type_mode(tmpdir):
    # type: (Tempdir) -> None

    directory = safe_mkdir(tmpdir.join("dir"))
    zip_dir = ZipFileType.from_path(directory)
    assert stat.S_ISDIR(zip_dir.deterministic_mode)
    assert 0o755 & zip_dir.deterministic_mode

    regular_file = touch(tmpdir.join("file"))
    zip_reg_file = ZipFileType.from_path(regular_file)
    assert stat.S_ISREG(zip_reg_file.deterministic_mode)
    assert 0o644 & zip_reg_file.deterministic_mode

    executable_file = touch(tmpdir.join("exe"))
    zip_exe_file = ZipFileType.from_path(executable_file)
    assert stat.S_ISREG(zip_exe_file.deterministic_mode)
    assert 0o755 & zip_exe_file.deterministic_mode


def extract_perms(path):
    # type: (str) -> str
    return oct(os.stat(path).st_mode)


@contextlib.contextmanager
def zip_fixture():
    # type: () -> Iterator[Tuple[str, str]]
    with temporary_dir() as target_dir:
        no_x = os.path.join(target_dir, "no-x")
        touch(no_x)

        no_w = os.path.join(target_dir, "no-w")
        touch(no_w)
        os.chmod(no_w, 0o444)

        with_x = os.path.join(target_dir, "with-x")
        touch(with_x)
        chmod_plus_x(with_x)

        assert extract_perms(no_x) != extract_perms(no_w) != extract_perms(with_x)

        zip_file = os.path.join(target_dir, "test.zip")
        with contextlib.closing(ZipFileEx(zip_file, "w")) as zf:
            zf.write(no_x, "no-x")
            zf.write(no_w, "no-w")
            zf.write(with_x, "with-x")

        yield zip_file, os.path.join(target_dir, "extract")


def is_writeable(path):
    # type: (str) -> bool
    return bool(os.stat(path).st_mode & 0o222)


def is_executable(path):
    # type: (str) -> bool
    return bool(os.stat(path).st_mode & 0o111)


def test_perm_preserving_zipfile_extractall():
    # type: () -> None
    with zip_fixture() as (zip_file, extract_dir):
        with contextlib.closing(ZipFileEx(zip_file)) as zf:
            zf.extractall(extract_dir)

            no_x = os.path.join(extract_dir, "no-x")
            no_w = os.path.join(extract_dir, "no-w")
            with_x = os.path.join(extract_dir, "with-x")

            assert not is_executable(no_x)
            assert not is_executable(no_w)
            assert is_executable(with_x)

            files = [no_x, no_w, with_x]
            assert all(is_writeable(f) for f in files)


def test_perm_preserving_zipfile_extract():
    # type: () -> None
    with zip_fixture() as (zip_file, extract_dir):
        with contextlib.closing(ZipFileEx(zip_file)) as zf:
            zf.extract("no-x", path=extract_dir)
            zf.extract("no-w", path=extract_dir)
            zf.extract("with-x", path=extract_dir)

            no_x = os.path.join(extract_dir, "no-x")
            no_w = os.path.join(extract_dir, "no-w")
            with_x = os.path.join(extract_dir, "with-x")

            assert not is_executable(no_x)
            assert not is_executable(no_w)
            assert is_executable(with_x)

            files = [no_x, no_w, with_x]
            assert all(is_writeable(f) for f in files)


def assert_chroot_perms(copyfn):
    with temporary_dir() as src:
        one = os.path.join(src, "one")
        touch(one)

        two = os.path.join(src, "two")
        touch(two)
        chmod_plus_x(two)

        with temporary_dir() as dst:
            chroot = Chroot(dst)
            copyfn(chroot, one, "one")
            copyfn(chroot, two, "two")
            assert extract_perms(one) == extract_perms(os.path.join(chroot.path(), "one"))
            assert extract_perms(two) == extract_perms(os.path.join(chroot.path(), "two"))

            zip_path = os.path.join(src, "chroot.zip")
            chroot.zip(zip_path)
            with temporary_dir() as extract_dir:
                with contextlib.closing(ZipFileEx(zip_path)) as zf:
                    zf.extractall(extract_dir)

                    assert not is_executable(os.path.join(extract_dir, "one"))
                    assert is_executable(os.path.join(extract_dir, "two"))


def test_chroot_perms_copy():
    # type: () -> None
    assert_chroot_perms(Chroot.copy)


def test_chroot_perms_link_same_device():
    # type: () -> None
    assert_chroot_perms(Chroot.link)


def test_chroot_perms_link_cross_device():
    # type: () -> None
    with mock.patch("os.link", spec_set=True, autospec=True) as mock_link:
        expected_errno = errno.EXDEV
        mock_link.side_effect = OSError(expected_errno, os.strerror(expected_errno))

        assert_chroot_perms(Chroot.link)


def test_chroot_zip():
    # type: () -> None
    with temporary_dir() as tmp:
        chroot = Chroot(os.path.join(tmp, "chroot"))
        chroot.write(b"data", "directory/subdirectory/file")
        zip_dst = os.path.join(tmp, "chroot.zip")
        chroot.zip(zip_dst)
        with open_zip(zip_dst) as zip:
            assert [
                "directory/",
                "directory/subdirectory/",
                "directory/subdirectory/file",
            ] == sorted(zip.namelist())
            assert b"" == zip.read("directory/")
            assert b"" == zip.read("directory/subdirectory/")
            assert b"data" == zip.read("directory/subdirectory/file")


def test_chroot_zip_is_deterministic():
    # type: () -> None
    with temporary_dir() as tmp:
        root_dir = os.path.join(tmp, "root")
        dir_a = os.path.join(root_dir, "a")
        src_path_a = os.path.join(dir_a, "file_a")
        touch(src_path_a)
        dir_b = os.path.join(root_dir, "b")
        src_path_b = os.path.join(dir_b, "file_b")
        touch(src_path_b)

        chroot = Chroot(os.path.join(tmp, "chroot"))
        chroot.symlink(root_dir, "root")

        zip_one_dst = os.path.join(tmp, "chroot_one.zip")
        zip_two_dst = os.path.join(tmp, "chroot_two.zip")

        with mock.patch("os.walk", new=NonDeterministicWalk()):
            chroot.zip(zip_one_dst)
            chroot.zip(zip_two_dst)

        with open_zip(zip_one_dst) as zip_file:
            namelist_one = zip_file.namelist()

        with open_zip(zip_two_dst) as zip_file:
            namelist_two = zip_file.namelist()

        assert namelist_one == namelist_two


def test_chroot_zip_symlink():
    # type: () -> None
    with temporary_dir() as tmp:
        chroot = Chroot(os.path.join(tmp, "chroot"))
        chroot.write(b"data", "directory/subdirectory/file")
        chroot.write(b"data", "directory/subdirectory/file.foo")
        chroot.symlink(
            os.path.join(chroot.path(), "directory/subdirectory/file"),
            "directory/subdirectory/symlinked",
        )

        cwd = os.getcwd()
        try:
            os.chdir(os.path.join(chroot.path(), "directory/subdirectory"))
            chroot.symlink(
                "file",
                "directory/subdirectory/rel-symlinked",
            )
        finally:
            os.chdir(cwd)

        chroot.symlink(os.path.join(chroot.path(), "directory"), "symlinked")
        zip_dst = os.path.join(tmp, "chroot.zip")
        chroot.zip(zip_dst, exclude_file=lambda path: path.endswith(".foo"))
        with open_zip(zip_dst) as zip:
            assert [
                "directory/",
                "directory/subdirectory/",
                "directory/subdirectory/file",
                "directory/subdirectory/rel-symlinked",
                "directory/subdirectory/symlinked",
                "symlinked/",
                "symlinked/subdirectory/",
                "symlinked/subdirectory/file",
                "symlinked/subdirectory/rel-symlinked",
                "symlinked/subdirectory/symlinked",
            ] == sorted(zip.namelist())
            assert b"" == zip.read("directory/")
            assert b"" == zip.read("directory/subdirectory/")
            assert b"data" == zip.read("directory/subdirectory/file")
            assert b"data" == zip.read("directory/subdirectory/rel-symlinked")
            assert b"data" == zip.read("directory/subdirectory/symlinked")
            assert b"" == zip.read("symlinked/")
            assert b"" == zip.read("symlinked/subdirectory/")
            assert b"data" == zip.read("symlinked/subdirectory/file")
            assert b"data" == zip.read("symlinked/subdirectory/rel-symlinked")
            assert b"data" == zip.read("symlinked/subdirectory/symlinked")


def test_deterministic_walk():
    # type: () -> None
    with temporary_dir() as tmp:
        root_dir = os.path.join(tmp, "root")
        dir_a = os.path.join(root_dir, "a")
        file_a = os.path.join(dir_a, "file_a")
        touch(file_a)
        dir_b = os.path.join(root_dir, "b")
        file_b = os.path.join(dir_b, "file_b")
        touch(file_b)

        with mock.patch("os.walk", new=NonDeterministicWalk()):
            result_a = []
            for root, dirs, files in deterministic_walk(root_dir):
                result_a.append((root, dirs, files))
                if dirs:
                    dirs[:] = ["b", "a"]

            result_b = []
            for root, dirs, files in deterministic_walk(root_dir):
                result_b.append((root, dirs, files))

        assert result_a == [
            (root_dir, ["a", "b"], []),
            (dir_a, [], ["file_a"]),
            (dir_b, [], ["file_b"]),
        ], "Modifying dirs should not affect the order of the walk"
        assert result_a == result_b, "Should be resilient to os.walk yielding in arbitrary order"


@pytest.fixture
def temporary_working_dir():
    # type: () -> Iterator[str]
    cwd = os.getcwd()
    try:
        with temporary_dir() as td:
            os.chdir(td)
            yield td
    finally:
        os.chdir(cwd)


def test_safe_open_abs(temporary_working_dir):
    # type: (str) -> None
    abs_path = os.path.join(temporary_working_dir, "path")
    with safe_open(abs_path, "w") as fp:
        fp.write("contents")

    with open(abs_path) as fp:
        assert "contents" == fp.read()


def test_safe_open_relative(temporary_working_dir):
    # type: (str) -> None
    rel_path = "rel_path"
    with safe_open(rel_path, "w") as fp:
        fp.write("contents")

    abs_path = os.path.join(temporary_working_dir, rel_path)
    with open(abs_path) as fp:
        assert "contents" == fp.read()
