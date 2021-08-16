# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import stat
import subprocess
import zipfile

import pytest

from pex.common import safe_open, temporary_dir
from pex.compatibility import WINDOWS
from pex.executor import Executor
from pex.pex import PEX
from pex.pex_builder import CopyMode, PEXBuilder
from pex.testing import built_wheel, make_bdist
from pex.testing import write_simple_pex as write_pex
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterator, List

exe_main = """
import sys
from p1.my_module import do_something
do_something()

with open(sys.argv[1], 'w') as fp:
  fp.write('success')
"""

wheeldeps_exe_main = """
import sys
from pyparsing import *
from p1.my_module import do_something
do_something()

with open(sys.argv[1], 'w') as fp:
  fp.write('success')
"""


def test_pex_builder():
    # type: () -> None
    # test w/ and w/o zipfile dists
    with temporary_dir() as td, make_bdist("p1") as p1:
        pb = write_pex(td, exe_main, dists=[p1])

        success_txt = os.path.join(td, "success.txt")
        PEX(td, interpreter=pb.interpreter).run(args=[success_txt])
        assert os.path.exists(success_txt)
        with open(success_txt) as fp:
            assert fp.read() == "success"

    # test w/ and w/o zipfile dists
    with temporary_dir() as td1, temporary_dir() as td2, make_bdist("p1") as p1:
        pb = write_pex(td1, exe_main, dists=[p1])

        success_txt = os.path.join(td1, "success.txt")
        PEX(td1, interpreter=pb.interpreter).run(args=[success_txt])
        assert os.path.exists(success_txt)
        with open(success_txt) as fp:
            assert fp.read() == "success"


def test_pex_builder_wheeldep():
    # type: () -> None
    """Repeat the pex_builder test, but this time include an import of something from a wheel that
    doesn't come in importable form."""
    with temporary_dir() as td, make_bdist("p1") as p1:
        pyparsing_path = "./tests/example_packages/pyparsing-2.1.10-py2.py3-none-any.whl"
        pb = write_pex(td, wheeldeps_exe_main, dists=[p1, pyparsing_path])
        success_txt = os.path.join(td, "success.txt")
        PEX(td, interpreter=pb.interpreter).run(args=[success_txt])
        assert os.path.exists(success_txt)
        with open(success_txt) as fp:
            assert fp.read() == "success"


def test_pex_builder_shebang():
    # type: () -> None
    def builder(shebang):
        # type: (str) -> PEXBuilder
        pb = PEXBuilder()
        pb.set_shebang(shebang)
        return pb

    for pb in builder("foobar"), builder("#!foobar"):
        for b in pb, pb.clone():
            with temporary_dir() as td:
                target = os.path.join(td, "foo.pex")
                b.build(target)
                expected_preamble = b"#!foobar\n"
                with open(target, "rb") as fp:
                    assert fp.read(len(expected_preamble)) == expected_preamble


def test_pex_builder_preamble():
    # type: () -> None
    with temporary_dir() as td:
        target = os.path.join(td, "foo.pex")
        should_create = os.path.join(td, "foo.1")

        tempfile_preamble = "\n".join(
            ["import sys", "open('{0}', 'w').close()".format(should_create), "sys.exit(3)"]
        )

        pb = PEXBuilder(preamble=tempfile_preamble)
        pb.build(target)

        assert not os.path.exists(should_create)

        pex = PEX(target, interpreter=pb.interpreter)
        process = pex.run(blocking=False)
        process.wait()

        assert process.returncode == 3
        assert os.path.exists(should_create)


def test_pex_builder_compilation():
    # type: () -> None
    with temporary_dir() as td1, temporary_dir() as td2, temporary_dir() as td3:
        src = os.path.join(td1, "src.py")
        with open(src, "w") as fp:
            fp.write(exe_main)

        exe = os.path.join(td1, "exe.py")
        with open(exe, "w") as fp:
            fp.write(exe_main)

        def build_and_check(path, precompile):
            # type: (str, bool) -> None
            pb = PEXBuilder(path=path)
            pb.add_source(src, "lib/src.py")
            pb.set_executable(exe, "exe.py")
            pb.freeze(bytecode_compile=precompile)
            for pyc_file in ("exe.pyc", "lib/src.pyc", "__main__.pyc"):
                pyc_exists = os.path.exists(os.path.join(path, pyc_file))
                if precompile:
                    assert pyc_exists
                else:
                    assert not pyc_exists
            bootstrap_dir = os.path.join(path, pb.info.bootstrap)
            bootstrap_pycs = []  # type: List[str]
            for _, _, files in os.walk(bootstrap_dir):
                bootstrap_pycs.extend(f for f in files if f.endswith(".pyc"))
            if precompile:
                assert len(bootstrap_pycs) > 0
            else:
                assert 0 == len(bootstrap_pycs)

        build_and_check(td2, False)
        build_and_check(td3, True)


@pytest.mark.skipif(WINDOWS, reason="No hardlinks on windows")
def test_pex_builder_copy_or_link():
    # type: () -> None
    with temporary_dir() as td:
        src = os.path.join(td, "exe.py")
        with safe_open(src, "w") as fp:
            fp.write(exe_main)

        def build_and_check(copy_mode):
            # type: (CopyMode.Value) -> None
            pb = PEXBuilder(copy_mode=copy_mode)
            path = pb.path()
            pb.add_source(src, "exe.py")

            path_clone = os.path.join(path, "__clone")
            pb.clone(into=path_clone)

            for root in path, path_clone:
                s1 = os.stat(src)
                s2 = os.stat(os.path.join(root, "exe.py"))
                is_link = (s1[stat.ST_INO], s1[stat.ST_DEV]) == (s2[stat.ST_INO], s2[stat.ST_DEV])
                if copy_mode == CopyMode.COPY:
                    assert not is_link
                else:
                    # Since os.stat follows symlinks; so in CopyMode.SYMLINK, this just proves
                    # the symlink points to the original file. Going further and checking path
                    # and path_clone for the presence of a symlink (an os.islink test) is
                    # trickier since a Linux hardlink of a symlink produces a symlink whereas a
                    # macOS hardlink of a symlink produces a hardlink.
                    assert is_link

        build_and_check(CopyMode.LINK)
        build_and_check(CopyMode.COPY)
        build_and_check(CopyMode.SYMLINK)


@pytest.fixture
def tmp_chroot(tmpdir):
    # type: (Any) -> Iterator[str]
    tmp_chroot = str(tmpdir)
    cwd = os.getcwd()
    try:
        os.chdir(tmp_chroot)
        yield tmp_chroot
    finally:
        os.chdir(cwd)


@pytest.mark.parametrize(
    "copy_mode", [pytest.param(copy_mode, id=copy_mode.value) for copy_mode in CopyMode.values]
)
def test_pex_builder_add_source_relpath_issues_1192(
    tmp_chroot,  # type: str
    copy_mode,  # type: CopyMode.Value
):
    # type: (...) -> None
    pb = PEXBuilder(copy_mode=copy_mode)
    with safe_open("src/main.py", "w") as fp:
        fp.write("import sys; sys.exit(42)")
    pb.add_source("src/main.py", "main.py")
    pb.set_entry_point("main")
    pb.build("test.pex")

    process = Executor.open_process(cmd=[os.path.abspath("test.pex")])
    process.wait()
    assert 42 == process.returncode


def test_pex_builder_deterministic_timestamp():
    # type: () -> None
    pb = PEXBuilder()
    with temporary_dir() as td:
        target = os.path.join(td, "foo.pex")
        pb.build(target, deterministic_timestamp=True)
        with zipfile.ZipFile(target) as zf:
            assert all(zinfo.date_time == (1980, 1, 1, 0, 0, 0) for zinfo in zf.infolist())


def test_pex_builder_from_requirements_pex():
    # type: () -> None
    def build_from_req_pex(path, req_pex):
        # type: (str, str) -> PEXBuilder
        pb = PEXBuilder(path=path)
        pb.add_from_requirements_pex(req_pex)
        with open(os.path.join(path, "exe.py"), "w") as fp:
            fp.write(exe_main)
        pb.set_executable(os.path.join(path, "exe.py"))
        pb.freeze()
        return pb

    def verify(pb):
        # type: (PEXBuilder) -> None
        success_txt = os.path.join(pb.path(), "success.txt")
        PEX(pb.path(), interpreter=pb.interpreter).run(args=[success_txt])
        assert os.path.exists(success_txt)
        with open(success_txt) as fp:
            assert fp.read() == "success"

    # Build from pex dir.
    with temporary_dir() as td2:
        with temporary_dir() as td1, make_bdist("p1") as p1:
            pb1 = write_pex(td1, dists=[p1])
            pb2 = build_from_req_pex(td2, pb1.path())
        verify(pb2)

    # Build from .pex file.
    with temporary_dir() as td4:
        with temporary_dir() as td3, make_bdist("p1") as p1:
            pb3 = write_pex(td3, dists=[p1])
            target = os.path.join(td3, "foo.pex")
            pb3.build(target)
            pb4 = build_from_req_pex(td4, target)
        verify(pb4)


def test_pex_builder_script_from_pex_path(tmpdir):
    # type: (Any) -> None

    pex_with_script = os.path.join(str(tmpdir), "script.pex")
    with built_wheel(
        name="my_project",
        entry_points={"console_scripts": ["my_app = my_project.my_module:do_something"]},
    ) as my_whl:
        pb = PEXBuilder()
        pb.add_dist_location(my_whl)
        pb.build(pex_with_script)

    pex_file = os.path.join(str(tmpdir), "app.pex")
    pb = PEXBuilder()
    pb.info.pex_path = pex_with_script
    pb.set_script("my_app")
    pb.build(pex_file)

    assert "hello world!\n" == subprocess.check_output(args=[pex_file]).decode("utf-8")


def test_pex_builder_setuptools_script(tmpdir):
    # type: (Any) -> None

    pex_file = os.path.join(str(tmpdir), "app.pex")
    with built_wheel(
        name="my_project",
    ) as my_whl:
        pb = PEXBuilder()
        pb.add_dist_location(my_whl)
        pb.set_script("shell_script")
        pb.build(pex_file)

    assert "hello world from shell script\n" == subprocess.check_output(args=[pex_file]).decode(
        "utf-8"
    )
