# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import pkgutil

import pytest

from pex.platforms import Platform
from pex.third_party.packaging import markers, tags
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Dict


EXPECTED_BASE = [("py27", "none", "any"), ("py2", "none", "any")]


def test_platform():
    # type: () -> None
    assert Platform("linux-x86_64", "cp", "27", "mu") == Platform(
        "linux_x86_64", "cp", "27", "cp27mu"
    )
    assert str(Platform("linux-x86_64", "cp", "27", "m")) == "linux_x86_64-cp-27-cp27m"


def test_platform_create():
    # type: () -> None
    assert Platform.create("linux-x86_64-cp-27-cp27mu") == Platform(
        "linux_x86_64", "cp", "27", "cp27mu"
    )
    assert Platform.create("linux-x86_64-cp-27-mu") == Platform(
        "linux_x86_64", "cp", "27", "cp27mu"
    )
    assert Platform.create("macosx-10.4-x86_64-cp-27-m") == Platform(
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
    # type: () -> None
    platform = Platform.create("macosx-10.13-x86_64-cp-36-m")

    # A golden file test. This could break if we upgrade Pip and it upgrades packaging which, from
    # time to time, corrects omissions in tag sets.
    golden_tags = pkgutil.get_data(__name__, "data/platforms/macosx_10_13_x86_64-cp-36-m.tags.txt")
    assert golden_tags is not None
    assert (
        tuple(
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


def test_platform_marker_environment():
    # type: () -> None
    platform = Platform.create("linux-x86_64-cp-37-cp37m")
    env_defaulted = platform.marker_environment(default_unknown=True)
    env_sparse = platform.marker_environment(default_unknown=False)

    assert set(env_sparse.items()).issubset(set(env_defaulted.items()))

    def evaluate_marker(
        expression,  # type: str
        environment,  # type: Dict[str, str]
    ):
        # type: (...) -> bool
        markers.default_environment = environment.copy
        return cast(bool, markers.Marker(expression).evaluate())

    def assert_known_marker(expression):
        # type: (str) -> None
        assert evaluate_marker(expression, env_defaulted)
        assert evaluate_marker(expression, env_sparse)

    assert_known_marker("python_version == '3.7'")
    assert_known_marker("implementation_name == 'cpython'")
    assert_known_marker("platform_system == 'Linux'")
    assert_known_marker("platform_machine == 'x86_64'")

    def assert_unknown_marker(expression):
        # type: (str) -> None
        assert not evaluate_marker(expression, env_defaulted)
        with pytest.raises(markers.UndefinedEnvironmentName):
            evaluate_marker(expression, env_sparse)

    assert_unknown_marker("python_full_version == '3.7.10'")
    assert_unknown_marker("platform_release == '5.12.12-arch1-1'")
    assert_unknown_marker("platform_version == '#1 SMP PREEMPT Fri, 18 Jun 2021 21:59:22 +0000'")


def test_platform_marker_environment_issue_1488():
    # type: () -> None

    def assert_platform_machine(
        expected,  # type: str
        platform,  # type: str
    ):
        assert expected == Platform.create(platform).marker_environment()["platform_machine"]

    assert_platform_machine("x86_64", "linux-x86_64-cp-37-cp37m")
    assert_platform_machine("x86_64", "manylinux1-x86_64-cp-37-cp37m")
    assert_platform_machine("x86_64", "manylinux2010-x86_64-cp-37-cp37m")
    assert_platform_machine("x86_64", "manylinux2014-x86_64-cp-37-cp37m")
    assert_platform_machine("x86_64", "manylinux_2_5-x86_64-cp-37-cp37m")
    assert_platform_machine("aarch64", "manylinux_2_77-aarch64-cp-37-cp37m")

    assert_platform_machine("x86_64", "macosx-10.15-x86_64-cp-38-m")
    assert_platform_machine("arm64", "macosx-11.0-arm64-cp-39-cp39")
