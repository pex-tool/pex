# Copyright 2017 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import re
from textwrap import dedent

import pytest

from pex.pep_425 import CompatibilityTags
from pex.platforms import PlatformSpec
from pex.resolve import abbreviated_platforms
from pex.third_party.packaging import tags
from testing import data

EXPECTED_BASE = [("py27", "none", "any"), ("py2", "none", "any")]


def test_platform():
    # type: () -> None
    assert PlatformSpec("linux-x86_64", "cp", "27", (2, 7), "mu") == PlatformSpec(
        "linux_x86_64", "cp", "27", (2, 7), "cp27mu"
    )
    assert PlatformSpec("linux-x86_64", "cp", "2.7", (2, 7), "mu") == PlatformSpec(
        "linux_x86_64", "cp", "2.7", (2, 7), "cp27mu"
    )

    assert str(PlatformSpec("linux-x86_64", "cp", "27", (2, 7), "m")) == "linux_x86_64-cp-27-cp27m"
    assert (
        str(PlatformSpec("linux-x86_64", "cp", "310", (3, 10), "cp310"))
        == "linux_x86_64-cp-310-cp310"
    )

    assert (
        str(PlatformSpec("linux-x86_64", "cp", "3.10", (3, 10), "cp310"))
        == "linux_x86_64-cp-3.10-cp310"
    )
    assert (
        str(PlatformSpec("linux-x86_64", "cp", "3.10.1", (3, 10, 1), "cp310"))
        == "linux_x86_64-cp-3.10.1-cp310"
    )


def test_platform_create():
    # type: () -> None
    assert PlatformSpec.parse("linux-x86_64-cp-27-cp27mu") == PlatformSpec(
        "linux_x86_64", "cp", "27", (2, 7), "cp27mu"
    )
    assert PlatformSpec.parse("linux-x86_64-cp-27-mu") == PlatformSpec(
        "linux_x86_64", "cp", "27", (2, 7), "cp27mu"
    )
    assert PlatformSpec.parse("macosx-10.4-x86_64-cp-27-m") == PlatformSpec(
        "macosx_10_4_x86_64",
        "cp",
        "27",
        (2, 7),
        "cp27m",
    )


def assert_raises(platform, expected_cause):
    with pytest.raises(
        PlatformSpec.InvalidSpecError,
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
        PlatformSpec.parse(platform)


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


def test_platform_supported_tags():
    # type: () -> None
    platform = abbreviated_platforms.create("macosx-10.13-x86_64-cp-36-m")

    # A golden file test. This could break if we upgrade Pip and it upgrades packaging which, from
    # time to time, corrects omissions in tag sets.
    golden_tags = data.load("platforms/macosx_10_13_x86_64-cp-36-m.tags.txt")
    assert golden_tags is not None
    assert (
        CompatibilityTags(
            itertools.chain.from_iterable(
                tags.parse_tag(tag)
                for tag in golden_tags.decode("utf-8").splitlines()
                if not tag.startswith("#")
            )
        )
        == platform.supported_tags
    )


def test_platform_supported_tags_manylinux():
    # type: () -> None
    tags = frozenset(abbreviated_platforms.create("linux-x86_64-cp-37-cp37m").supported_tags)
    manylinux1_tags = frozenset(
        abbreviated_platforms.create(
            "linux-x86_64-cp-37-cp37m", manylinux="manylinux1"
        ).supported_tags
    )
    manylinux2010_tags = frozenset(
        abbreviated_platforms.create(
            "linux-x86_64-cp-37-cp37m", manylinux="manylinux2010"
        ).supported_tags
    )
    manylinux2014_tags = frozenset(
        abbreviated_platforms.create(
            "linux-x86_64-cp-37-cp37m", manylinux="manylinux2014"
        ).supported_tags
    )
    assert manylinux2014_tags > manylinux2010_tags > manylinux1_tags > tags
