# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pex.platforms import Platform

EXPECTED_BASE = [("py27", "none", "any"), ("py2", "none", "any")]


def test_platform():
    # type: () -> None
    assert Platform("linux-x86_64", "cp", "27", "mu") == ("linux_x86_64", "cp", "27", "cp27mu")
    assert str(Platform("linux-x86_64", "cp", "27", "m")) == "linux_x86_64-cp-27-cp27m"


def test_platform_create():
    # type: () -> None
    assert Platform.create("linux-x86_64-cp-27-cp27mu") == ("linux_x86_64", "cp", "27", "cp27mu")
    assert Platform.create("linux-x86_64-cp-27-mu") == ("linux_x86_64", "cp", "27", "cp27mu")
    assert Platform.create("macosx-10.4-x86_64-cp-27-m") == (
        "macosx_10_4_x86_64",
        "cp",
        "27",
        "cp27m",
    )


def test_platform_create_bad_platform_missing_fields():
    # type: () -> None
    with pytest.raises(Platform.InvalidPlatformError):
        Platform.create("linux-x86_64")


def test_platform_create_bad_platform_empty_fields():
    # type: () -> None
    with pytest.raises(Platform.InvalidPlatformError):
        Platform.create("linux-x86_64-cp--cp27mu")


def test_platform_create_noop():
    # type: () -> None
    existing = Platform.create("linux-x86_64-cp-27-mu")
    assert Platform.create(existing) == existing
