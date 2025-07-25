# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.interpreter import PythonInterpreter
from pex.pep_376 import InstalledFile, find_and_replace_path_components
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


def test_filter_path_invalid():
    # type: () -> None

    with pytest.raises(ValueError):
        find_and_replace_path_components("foo", "bar", "")
        find_and_replace_path_components("foo", "", "baz")


def test_filter_path_noop():
    # type: () -> None

    assert "" == find_and_replace_path_components("", "spam", "eggs")
    assert "." == find_and_replace_path_components(".", "spam", "eggs")
    assert ".." == find_and_replace_path_components("..", "spam", "eggs")
    assert "/" == find_and_replace_path_components("/", "spam", "eggs")
    assert "foo/bar/baz" == find_and_replace_path_components("foo/bar/baz", "spam", "eggs")


def test_filter_path_basic():
    # type: () -> None

    assert "spam/bar/baz" == find_and_replace_path_components("foo/bar/baz", "foo", "spam")
    assert "foo/spam/baz" == find_and_replace_path_components("foo/bar/baz", "bar", "spam")
    assert "foo/bar/spam" == find_and_replace_path_components("foo/bar/baz", "baz", "spam")


def test_filter_path_absolute():
    # type: () -> None

    assert "/spam/bar/baz" == find_and_replace_path_components("/foo/bar/baz", "foo", "spam")


def test_filter_path_relative():
    # type: () -> None

    assert "../spam/bar/baz" == find_and_replace_path_components("../foo/bar/baz", "foo", "spam")
    assert "./spam/bar/baz" == find_and_replace_path_components("./foo/bar/baz", "foo", "spam")
    assert "/spam/../bar/./baz" == find_and_replace_path_components(
        "/foo/../bar/./baz", "foo", "spam"
    )


def test_installed_file_path_normalization_noop(
    py39,  # type: PythonInterpreter
    py311,  # type: PythonInterpreter
):
    # type: (...) -> None

    def assert_noop(interpreter=None):
        # type: (Optional[PythonInterpreter]) -> None
        assert "foo/bar" == InstalledFile.normalized_path("foo/bar", interpreter=interpreter)
        assert "foo/python2.0" == InstalledFile.normalized_path(
            "foo/python2.0", interpreter=interpreter
        )
        assert "foo/bar" == InstalledFile.denormalized_path("foo/bar", interpreter=interpreter)

    assert_noop()
    assert_noop(py39)
    assert_noop(py311)


def test_installed_file_path_normalization_nominal(
    py39,  # type: PythonInterpreter
    py311,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert "foo/pythonX.Y/bar" == InstalledFile.normalized_path(
        "foo/python3.9/bar", interpreter=py39
    )
    assert "foo/pythonX.Y/bar" == InstalledFile.normalized_path(
        "foo/python3.11/bar", interpreter=py311
    )

    assert "foo/python3.9/bar" == InstalledFile.denormalized_path(
        "foo/pythonX.Y/bar", interpreter=py39
    )
    assert "foo/python3.11/bar" == InstalledFile.denormalized_path(
        "foo/pythonX.Y/bar", interpreter=py311
    )
