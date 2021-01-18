# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import pkgutil

import pytest

from pex.platforms import Platform
from pex.third_party.packaging import tags

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
    assert Platform.create(existing) is existing


def test_platform_supported_tags():
    platform = Platform.create("macosx-10.13-x86_64-cp-36-m")

    # A golden file test. This could break if we upgrade Pip and it upgrades packaging which, from
    # time to time, corrects omissions in tag sets.
    assert (
        tuple(
            itertools.chain.from_iterable(
                tags.parse_tag(tag)
                for tag in pkgutil.get_data(
                    __name__, "data/platforms/macosx_10_13_x86_64-cp-36-m.tags.txt"
                )
                .decode("utf-8")
                .splitlines()
                if not tag.startswith("#")
            )
        )
        == platform.supported_tags()
    )


def test_platform_supported_tags_manylinux():
    platform = Platform.create("linux-x86_64-cp-37-cp37m")
    tags = frozenset(platform.supported_tags())
    manylinux1_tags = frozenset(platform.supported_tags(manylinux="manylinux1"))
    manylinux2010_tags = frozenset(platform.supported_tags(manylinux="manylinux2010"))
    manylinux2014_tags = frozenset(platform.supported_tags(manylinux="manylinux2014"))
    assert manylinux2014_tags > manylinux2010_tags > manylinux1_tags > tags
