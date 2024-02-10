# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from hashlib import sha1
from textwrap import dedent

import pytest

from pex.common import safe_mkdir, safe_open, temporary_dir, touch
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper, DistributionHelper, named_temporary_file

if TYPE_CHECKING:
    from typing import Callable

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]


def test_access_zipped_assets():
    # type: (...) -> None
    pex_third_party_asset_dir = DistributionHelper.access_zipped_assets("pex", "third_party")

    resources = os.listdir(pex_third_party_asset_dir)
    assert (
        len(resources) > 0
    ), "The pex.third_party package should contain at least an __init__.py file."
    resources.remove("__init__.py")
    for path in resources:
        assert path in (
            "__init__.pyc",
            "__init__.pyo",
            "__pycache__",
        ), "Expected only __init__.py (and its compilations) in the pex.third_party package."


def test_hash():
    # type: () -> None
    empty_hash_digest = sha1().hexdigest()

    with named_temporary_file() as fp:
        fp.flush()
        assert empty_hash_digest == CacheHelper.hash(fp.name)

    with named_temporary_file() as fp:
        string = b"asdf" * 1024 * sha1().block_size + b"extra padding"
        fp.write(string)
        fp.flush()
        assert sha1(string).hexdigest() == CacheHelper.hash(fp.name)

    with named_temporary_file() as fp:
        empty_hash = sha1()
        fp.write(b"asdf")
        fp.flush()
        hash_output = CacheHelper.hash(fp.name, digest=empty_hash)
        assert hash_output == empty_hash.hexdigest()


@pytest.mark.parametrize(
    ("hasher", "includes_hidden_expected"),
    [(CacheHelper.dir_hash, True), (CacheHelper.pex_code_hash, False)],
)
def test_directory_hasher(hasher, includes_hidden_expected):
    # type: (Callable[[str], str], bool) -> None
    with temporary_dir() as tmp_dir:
        safe_mkdir(os.path.join(tmp_dir, "a", "b"))
        with safe_open(os.path.join(tmp_dir, "c", "d", "e.py"), "w") as fp:
            fp.write("contents1")
        with safe_open(os.path.join(tmp_dir, "f.py"), "w") as fp:
            fp.write("contents2")
        hash1 = hasher(tmp_dir)

        os.rename(os.path.join(tmp_dir, "c"), os.path.join(tmp_dir, "c-renamed"))
        assert hash1 != hasher(tmp_dir)

        os.rename(os.path.join(tmp_dir, "c-renamed"), os.path.join(tmp_dir, "c"))
        assert hash1 == hasher(tmp_dir)

        touch(os.path.join(tmp_dir, "c", "d", "e.pyc"))
        assert hash1 == hasher(tmp_dir)
        touch(os.path.join(tmp_dir, "c", "d", "e.pyc.123456789"))
        assert hash1 == hasher(tmp_dir)

        pycache_dir = os.path.join(tmp_dir, "__pycache__")
        safe_mkdir(pycache_dir)
        touch(os.path.join(pycache_dir, "f.pyc"))
        assert hash1 == hasher(tmp_dir)
        touch(os.path.join(pycache_dir, "f.pyc.123456789"))
        assert hash1 == hasher(tmp_dir)

        touch(os.path.join(pycache_dir, "f.py"))
        assert hash1 == hasher(
            tmp_dir
        ), "All content under __pycache__ directories should be ignored."

        with safe_open(os.path.join(tmp_dir, ".hidden"), "w") as fp:
            fp.write("contents3")

        includes_hidden = hash1 != hasher(tmp_dir)
        assert includes_hidden == includes_hidden_expected


try:
    import __builtin__ as python_builtins  # type: ignore[import]
except ImportError:
    import builtins as python_builtins  # type: ignore[no-redef]


def assert_access_zipped_assets(distribution_helper_import):
    # type: (str) -> bytes
    test_executable = dedent(
        """
        import os
        {distribution_helper_import}
        temp_dir = DistributionHelper.access_zipped_assets('my_package', 'submodule')
        with open(os.path.join(temp_dir, 'mod.py'), 'r') as fp:
            for line in fp:
                print(line)
        """.format(
            distribution_helper_import=distribution_helper_import
        )
    )
    with temporary_dir() as td1, temporary_dir() as td2:
        pb = PEXBuilder(path=td1)
        with open(os.path.join(td1, "exe.py"), "w") as fp:
            fp.write(test_executable)
            pb.set_executable(fp.name)

        submodule = os.path.join(td1, "my_package", "submodule")
        safe_mkdir(submodule)
        mod_path = os.path.join(submodule, "mod.py")
        with open(mod_path, "w") as fp:
            fp.write("accessed")
            pb.add_source(fp.name, "my_package/submodule/mod.py")
        pb.add_source(None, "my_package/__init__.py")
        pb.add_source(None, "my_package/submodule/__init__.py")
        pex = os.path.join(td2, "app.pex")
        pb.build(pex)

        process = PEX(pex, interpreter=pb.interpreter).run(
            blocking=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()
        assert process.returncode == 0
        assert b"accessed\n" == stdout
        return cast(bytes, stderr)


def test_access_zipped_assets_integration():
    # type: () -> None
    stderr = assert_access_zipped_assets("from pex.util import DistributionHelper")
    assert b"" == stderr.strip()


def test_named_temporary_file():
    # type: () -> None
    with named_temporary_file() as fp:
        name = fp.name
        fp.write(b"hi")
        fp.flush()
        assert os.path.exists(name)
        with open(name) as new_fp:
            assert new_fp.read() == "hi"

    assert not os.path.exists(name)
