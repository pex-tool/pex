# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import pkgutil
import re
from textwrap import dedent

import pytest

from pex.pep_425 import CompatibilityTags
from pex.platforms import Platform
from pex.third_party.packaging import tags

EXPECTED_BASE = [("py27", "none", "any"), ("py2", "none", "any")]


def test_platform():
    # type: () -> None
    assert Platform("linux-x86_64", "cp", "27", (2, 7), "mu") == Platform(
        "linux_x86_64", "cp", "27", (2, 7), "cp27mu"
    )
    assert Platform("linux-x86_64", "cp", "2.7", (2, 7), "mu") == Platform(
        "linux_x86_64", "cp", "2.7", (2, 7), "cp27mu"
    )

    assert str(Platform("linux-x86_64", "cp", "27", (2, 7), "m")) == "linux_x86_64-cp-27-cp27m"
    assert (
        str(Platform("linux-x86_64", "cp", "310", (3, 10), "cp310")) == "linux_x86_64-cp-310-cp310"
    )

    assert (
        str(Platform("linux-x86_64", "cp", "3.10", (3, 10), "cp310"))
        == "linux_x86_64-cp-3.10-cp310"
    )
    assert (
        str(Platform("linux-x86_64", "cp", "3.10.1", (3, 10, 1), "cp310"))
        == "linux_x86_64-cp-3.10.1-cp310"
    )


def test_platform_create():
    # type: () -> None
    assert Platform.create("linux-x86_64-cp-27-cp27mu") == Platform(
        "linux_x86_64", "cp", "27", (2, 7), "cp27mu"
    )
    assert Platform.create("linux-x86_64-cp-27-mu") == Platform(
        "linux_x86_64", "cp", "27", (2, 7), "cp27mu"
    )
    assert Platform.create("macosx-10.4-x86_64-cp-27-m") == Platform(
        "macosx_10_4_x86_64",
        "cp",
        "27",
        (2, 7),
        "cp27m",
    )


def assert_raises(platform, expected_cause):
    with pytest.raises(
        Platform.InvalidPlatformError,
        match=(
            r".*{literal}.*".format(
                literal=re.escape(
                    dedent(
                        """\
                        Not a valid platform specifier: {platform}
                        
                        {expected_cause}
                        """
                    ).format(platform=platform, expected_cause=expected_cause)
                )
            )
        ),
    ):
        Platform.create(platform)


def test_platform_create_bad_platform_missing_fields():
    # type: () -> None
    assert_raises(
        platform="linux_x86_64",
        expected_cause="There are missing platform fields. Expected 4 but given 1.",
    )


def test_platform_create_bad_platform_empty_fields():
    # type: () -> None
    assert_raises(
        platform="linux_x86_64--27-cp27mu",
        expected_cause="Platform specifiers cannot have blank fields. Given a blank impl.",
    )


def test_platform_create_bad_platform_bad_version():
    # type: () -> None
    assert_raises(
        platform="linux_x86_64-cp-2-cp27mu",
        expected_cause=(
            "The version field must either be a 2 or more digit digit major/minor version or else "
            "a component dotted version. Given: '2'"
        ),
    )

    assert_raises(
        platform="linux_x86_64-cp-XY-cp27mu",
        expected_cause="The version specified had non-integer components. Given: 'XY'",
    )

    assert_raises(
        platform="linux_x86_64-cp-2.-cp27mu",
        expected_cause="The version specified had non-integer components. Given: '2.'",
    )

    assert_raises(
        platform="linux_x86_64-cp-2.Y-cp27mu",
        expected_cause="The version specified had non-integer components. Given: '2.Y'",
    )


def test_platform_create_noop():
    # type: () -> None
    existing = Platform.create("linux-x86_64-cp-27-mu")
    assert Platform.create(existing) is existing


def test_platform_supported_tags():
    # type: () -> None
    platform = Platform.create("macosx-10.13-x86_64-cp-36-m")

    # A golden file test. This could break if we upgrade Pip and it upgrades packaging which, from
    # time to time, corrects omissions in tag sets.
    golden_tags = pkgutil.get_data(__name__, "data/platforms/macosx_10_13_x86_64-cp-36-m.tags.txt")
    assert golden_tags is not None
    assert (
        CompatibilityTags(
            itertools.chain.from_iterable(
                tags.parse_tag(tag)
                for tag in golden_tags.decode("utf-8").splitlines()
                if not tag.startswith("#")
            )
        )
        == platform.supported_tags()
    )


def test_platform_supported_tags_manylinux():
    # type: () -> None
    platform = Platform.create("linux-x86_64-cp-37-cp37m")
    tags = frozenset(platform.supported_tags())
    manylinux1_tags = frozenset(platform.supported_tags(manylinux="manylinux1"))
    manylinux2010_tags = frozenset(platform.supported_tags(manylinux="manylinux2010"))
    manylinux2014_tags = frozenset(platform.supported_tags(manylinux="manylinux2014"))
    assert manylinux2014_tags > manylinux2010_tags > manylinux1_tags > tags
