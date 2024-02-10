# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

import pytest

from pex.resolve.path_mappings import PathMapping, PathMappings
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Tuple


def create_path_mappings(*mappings):
    # type: (*Tuple[str, str]) -> PathMappings
    return PathMappings(tuple(PathMapping(path=path, name=name) for path, name in mappings))


def test_invalid():
    # type: () -> None

    with pytest.raises(ValueError, match=re.escape("Mapped paths must be absolute. Given: foo")):
        create_path_mappings(("./foo", "A"))


def test_normalize():
    # type: () -> None

    def check_path(
        path_mappings,  # type: PathMappings
        expected_path,  # type: str
    ):
        # type: (...) -> PathMappings
        assert 1 == len(path_mappings.mappings)
        assert expected_path == path_mappings.mappings[0].path
        return path_mappings

    assert check_path(create_path_mappings(("/tmp/foo", "A")), "/tmp/foo") == check_path(
        create_path_mappings(("/tmp/./foo/", "A")), "/tmp/foo"
    )


def test_noop():
    # type: () -> None

    path_mappings = create_path_mappings(("/tmp/foo", "A"))

    assert "foo" == path_mappings.maybe_canonicalize("foo")
    assert "/tmp/bar" == path_mappings.maybe_canonicalize("/tmp/bar")

    assert "foo" == path_mappings.maybe_reify("foo")
    assert "/tmp/foo" == path_mappings.maybe_reify("/tmp/foo")
    assert "A" == path_mappings.maybe_reify("A")
    assert "$A" == path_mappings.maybe_reify("$A")


def test_canonicalize():
    # type: () -> None

    path_mappings = create_path_mappings(("/tmp/foo", "A"), ("/tmp/bar/", "B"))

    assert "${A}" == path_mappings.maybe_canonicalize("/tmp/foo")
    assert "${B}/" == path_mappings.maybe_canonicalize("/tmp/bar/")
    assert "${A}/bar" == path_mappings.maybe_canonicalize("/tmp/foo/bar")

    assert "file://${A}/bar" == path_mappings.maybe_canonicalize("file:///tmp/foo/bar")
    assert "baz @ file://${B}/baz" == path_mappings.maybe_canonicalize("baz @ file:///tmp/bar/baz")


def test_reify():
    # type: () -> None

    path_mappings = create_path_mappings(("/tmp/foo", "A"), ("/tmp/bar/", "B"))

    assert "/tmp/foo" == path_mappings.maybe_reify("${A}")
    assert "/tmp/bar/" == path_mappings.maybe_reify("${B}/")
    assert "/tmp/foo/bar" == path_mappings.maybe_reify("${A}/bar")

    assert "file:///tmp/foo/bar" == path_mappings.maybe_reify("file://${A}/bar")
    assert "baz @ file:///tmp/bar/baz" == path_mappings.maybe_reify("baz @ file://${B}/baz")
