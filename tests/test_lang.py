# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.atomic_directory import AtomicDirectory
from pex.common import ZipFileEx
from pex.compatibility import PY2
from pex.lang import qualified_name


def test_qualified_name():
    # type: () -> None

    expected_str_type = "{module}.str".format(module="__builtin__" if PY2 else "builtins")
    assert expected_str_type == qualified_name(str), "Expected builtin types to be handled."
    assert expected_str_type == qualified_name(
        "foo"
    ), "Expected non-callable objects to be identified via their types."

    assert "pex.lang.qualified_name" == qualified_name(
        qualified_name
    ), "Expected functions to be handled"

    assert "pex.atomic_directory.AtomicDirectory" == qualified_name(
        AtomicDirectory
    ), "Expected custom types to be handled."
    expected_prefix = "pex.atomic_directory." if PY2 else "pex.atomic_directory.AtomicDirectory."
    assert expected_prefix + "finalize" == qualified_name(
        AtomicDirectory.finalize
    ), "Expected methods to be handled."
    assert expected_prefix + "work_dir" == qualified_name(
        AtomicDirectory.work_dir
    ), "Expected @property to be handled."

    expected_prefix = "pex.common." if PY2 else "pex.common.ZipFileEx."
    assert expected_prefix + "zip_info_from_file" == qualified_name(
        ZipFileEx.zip_info_from_file
    ), "Expected @classmethod to be handled."

    class Test(object):
        @staticmethod
        def static():
            pass

    expected_prefix = "test_lang." if PY2 else "test_lang.test_qualified_name.<locals>.Test."
    assert expected_prefix + "static" == qualified_name(
        Test.static
    ), "Expected @staticmethod to be handled."
