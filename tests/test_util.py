# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from hashlib import sha1
from textwrap import dedent

from pex.common import safe_mkdir, safe_open, temporary_dir, touch
from pex.compatibility import nested, to_bytes
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper, DistributionHelper, iter_pth_paths, named_temporary_file

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef]

if TYPE_CHECKING:
    from typing import Any, Dict, List


@mock.patch("pex.util.safe_mkdtemp", autospec=True, spec_set=True)
@mock.patch("pex.util.safe_mkdir", autospec=True, spec_set=True)
@mock.patch("pex.util.resource_listdir", autospec=True, spec_set=True)
@mock.patch("pex.util.resource_isdir", autospec=True, spec_set=True)
@mock.patch("pex.util.resource_string", autospec=True, spec_set=True)
def test_access_zipped_assets(
    mock_resource_string,  # type: Any
    mock_resource_isdir,  # type: Any
    mock_resource_listdir,  # type: Any
    mock_safe_mkdir,  # type: Any
    mock_safe_mkdtemp,  # type: Any
):
    # type: (...) -> None
    mock_open = mock.mock_open()
    mock_safe_mkdtemp.side_effect = iter(["tmpJIMMEH", "faketmpDir"])
    mock_resource_listdir.side_effect = iter([["./__init__.py", "./directory/"], ["file.py"]])
    mock_resource_isdir.side_effect = iter([False, True, False])
    mock_resource_string.return_value = "testing"

    with mock.patch("%s.open" % python_builtins.__name__, mock_open, create=True):
        temp_dir = DistributionHelper.access_zipped_assets("twitter.common", "dirutil")
        assert mock_resource_listdir.call_count == 2
        assert mock_open.call_count == 2
        file_handle = mock_open.return_value.__enter__.return_value
        assert file_handle.write.call_count == 2
        assert mock_safe_mkdtemp.mock_calls == [mock.call()]
        assert temp_dir == "tmpJIMMEH"
        assert mock_safe_mkdir.mock_calls == [mock.call(os.path.join("tmpJIMMEH", "directory"))]


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


def test_dir_hash():
    # type: () -> None
    with temporary_dir() as tmp_dir:
        safe_mkdir(os.path.join(tmp_dir, "a", "b"))
        with safe_open(os.path.join(tmp_dir, "c", "d", "e.py"), "w") as fp:
            fp.write("contents1")
        with safe_open(os.path.join(tmp_dir, "f.py"), "w") as fp:
            fp.write("contents2")
        hash1 = CacheHelper.dir_hash(tmp_dir)

        os.rename(os.path.join(tmp_dir, "c"), os.path.join(tmp_dir, "c-renamed"))
        assert hash1 != CacheHelper.dir_hash(tmp_dir)

        os.rename(os.path.join(tmp_dir, "c-renamed"), os.path.join(tmp_dir, "c"))
        assert hash1 == CacheHelper.dir_hash(tmp_dir)

        touch(os.path.join(tmp_dir, "c", "d", "e.pyc"))
        assert hash1 == CacheHelper.dir_hash(tmp_dir)
        touch(os.path.join(tmp_dir, "c", "d", "e.pyc.123456789"))
        assert hash1 == CacheHelper.dir_hash(tmp_dir)

        pycache_dir = os.path.join(tmp_dir, "__pycache__")
        safe_mkdir(pycache_dir)
        touch(os.path.join(pycache_dir, "f.pyc"))
        assert hash1 == CacheHelper.dir_hash(tmp_dir)
        touch(os.path.join(pycache_dir, "f.pyc.123456789"))
        assert hash1 == CacheHelper.dir_hash(tmp_dir)

        touch(os.path.join(pycache_dir, "f.py"))
        assert hash1 == CacheHelper.dir_hash(
            tmp_dir
        ), "All content under __pycache__ directories should be ignored."


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
    with nested(temporary_dir(), temporary_dir()) as (td1, td2):
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


@mock.patch("os.path.exists", autospec=True, spec_set=True)
def test_iter_pth_paths(mock_exists):
    # type: (Any) -> None
    # Ensure path checking always returns True for dummy paths.
    mock_exists.return_value = True

    with temporary_dir() as tmpdir:
        in_tmp = lambda f: os.path.join(tmpdir, f)

        PTH_TEST_MAPPING = {
            # A mapping of .pth file content -> expected paths.
            "/System/Library/Frameworks/Python.framework/Versions/2.7/Extras/lib/python\n": [
                "/System/Library/Frameworks/Python.framework/Versions/2.7/Extras/lib/python"
            ],
            "relative_path\nrelative_path2\n\nrelative_path3": [
                in_tmp("relative_path"),
                in_tmp("relative_path2"),
                in_tmp("relative_path3"),
            ],
            "duplicate_path\nduplicate_path": [in_tmp("duplicate_path")],
            "randompath\nimport nosuchmodule\n": [in_tmp("randompath")],
            "import sys\nfoo\n/bar/baz": [in_tmp("foo"), "/bar/baz"],
            "import nosuchmodule\nfoo": [],
            "import nosuchmodule\n": [],
            "import bad)syntax\n": [],
        }  # type: Dict[str, List[str]]

        for i, pth_content in enumerate(PTH_TEST_MAPPING):
            pth_tmp_path = os.path.abspath(os.path.join(tmpdir, "test%s.pth" % i))
            with open(pth_tmp_path, "wb") as f:
                f.write(to_bytes(pth_content))
            assert sorted(PTH_TEST_MAPPING[pth_content]) == sorted(
                list(iter_pth_paths(pth_tmp_path))
            )
