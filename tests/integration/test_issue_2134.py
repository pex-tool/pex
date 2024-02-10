# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

import pytest

from pex import layout
from pex.common import open_zip, touch
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any, Iterable, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class SourceTree(object):
    base_dir = attr.ib()  # type: str

    def create(self, offset=None):
        # type: (Optional[str]) -> str

        project_dir = os.path.join(self.base_dir, "project")
        source_root = os.path.join(project_dir, offset) if offset else project_dir

        touch(os.path.join(source_root, "top_level_module.py"))

        touch(os.path.join(source_root, "top_level_package_classic", "__init__.py"))
        touch(os.path.join(source_root, "top_level_package_classic", "module.py"))
        touch(os.path.join(source_root, "top_level_package_classic", "sub", "__init__.py"))
        touch(os.path.join(source_root, "top_level_package_classic", "sub", "foo.py"))
        touch(os.path.join(source_root, "top_level_package_classic", "sub", "bar.py"))

        # N.B.: This test will run against a range of interpreters, some supporting PEP420 and some
        # not, so we never import code in the tests that use this fixture and instead just check
        # file lists,
        touch(os.path.join(source_root, "top_level_package_pep420", "module.py"))
        touch(os.path.join(source_root, "top_level_package_pep420", "sub", "module.py"))

        touch(os.path.join(source_root, "top_level_package_mixed", "module.py"))
        touch(os.path.join(source_root, "top_level_package_mixed", "sub", "__init__.py"))
        touch(os.path.join(source_root, "top_level_package_mixed", "sub", "module.py"))

        subprocess.check_call(args=[sys.executable, "-m", "compileall", source_root])

        return project_dir

    def assert_sources(
        self,
        pex_args,  # type: Iterable[str]
        expected_sources,  # type: Iterable[str]
        offset=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        pex = os.path.join(self.base_dir, "pex")
        args = ["-o", pex]
        args.extend(pex_args)
        run_pex_command(args=args, cwd=self.create(offset=offset)).assert_success()

        with open_zip(pex) as zf:
            actual_sources = [
                f
                for f in zf.namelist()
                if not f.startswith((layout.BOOTSTRAP_DIR, layout.DEPS_DIR, "__pex__"))
                and f not in (layout.PEX_INFO_PATH, "__main__.py")
            ]

        assert sorted(expected_sources) == sorted(actual_sources)


@pytest.fixture
def source_tree(tmpdir):
    # type: (Any) -> SourceTree
    return SourceTree(str(tmpdir))


def test_add_top_level_package(source_tree):
    # type: (SourceTree) -> None
    source_tree.assert_sources(
        pex_args=["-P", "top_level_package_classic"],
        expected_sources=[
            "top_level_package_classic/",
            "top_level_package_classic/__init__.py",
            "top_level_package_classic/module.py",
            "top_level_package_classic/sub/",
            "top_level_package_classic/sub/__init__.py",
            "top_level_package_classic/sub/foo.py",
            "top_level_package_classic/sub/bar.py",
        ],
    )


def test_add_sub_package(source_tree):
    # type: (SourceTree) -> None
    source_tree.assert_sources(
        pex_args=["-P", "top_level_package_classic.sub"],
        expected_sources=[
            "top_level_package_classic/",
            "top_level_package_classic/__init__.py",
            "top_level_package_classic/sub/",
            "top_level_package_classic/sub/__init__.py",
            "top_level_package_classic/sub/foo.py",
            "top_level_package_classic/sub/bar.py",
        ],
    )


def test_add_sub_package_pep_420(source_tree):
    # type: (SourceTree) -> None
    source_tree.assert_sources(
        pex_args=["-P", "top_level_package_pep420.sub"],
        expected_sources=[
            "top_level_package_pep420/",
            "top_level_package_pep420/sub/",
            "top_level_package_pep420/sub/module.py",
        ],
    )


def test_add_sub_package_mixed(source_tree):
    # type: (SourceTree) -> None
    source_tree.assert_sources(
        pex_args=["-P", "top_level_package_mixed.sub"],
        expected_sources=[
            "top_level_package_mixed/",
            "top_level_package_mixed/sub/",
            "top_level_package_mixed/sub/__init__.py",
            "top_level_package_mixed/sub/module.py",
        ],
    )


def test_add_package_offset(source_tree):
    # type: (SourceTree) -> None
    source_tree.assert_sources(
        pex_args=["-P", "top_level_package_classic.sub@src"],
        offset="src",
        expected_sources=[
            "top_level_package_classic/",
            "top_level_package_classic/__init__.py",
            "top_level_package_classic/sub/",
            "top_level_package_classic/sub/__init__.py",
            "top_level_package_classic/sub/foo.py",
            "top_level_package_classic/sub/bar.py",
        ],
    )


def test_add_top_level_module(source_tree):
    # type: (SourceTree) -> None
    source_tree.assert_sources(
        pex_args=["-M", "top_level_module"], expected_sources=["top_level_module.py"]
    )


def test_add_module_in_package(source_tree):
    # type: (SourceTree) -> None
    source_tree.assert_sources(
        pex_args=["-M", "top_level_package_classic.sub.foo"],
        expected_sources=[
            "top_level_package_classic/",
            "top_level_package_classic/__init__.py",
            "top_level_package_classic/sub/",
            "top_level_package_classic/sub/__init__.py",
            "top_level_package_classic/sub/foo.py",
        ],
    )


def test_add_module_offset(source_tree):
    # type: (SourceTree) -> None
    offset = os.path.join("src", "python")
    source_tree.assert_sources(
        pex_args=["-M", "top_level_package_classic.sub.bar@{offset}".format(offset=offset)],
        offset=offset,
        expected_sources=[
            "top_level_package_classic/",
            "top_level_package_classic/__init__.py",
            "top_level_package_classic/sub/",
            "top_level_package_classic/sub/__init__.py",
            "top_level_package_classic/sub/bar.py",
        ],
    )


def test_overlap(source_tree):
    # type: (SourceTree) -> None
    source_tree.assert_sources(
        pex_args=[
            "-M",
            "top_level_package_classic.sub.foo@src",
            "-P",
            "top_level_package_classic.sub@src",
        ],
        offset="src",
        expected_sources=[
            "top_level_package_classic/",
            "top_level_package_classic/__init__.py",
            "top_level_package_classic/sub/",
            "top_level_package_classic/sub/__init__.py",
            "top_level_package_classic/sub/foo.py",
            "top_level_package_classic/sub/bar.py",
        ],
    )
