# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.dependency_configuration import DependencyConfiguration, Override
from pex.dist_metadata import Requirement
from pex.pep_503 import ProjectName


def test_override_parse():
    # type: () -> None

    def assert_cowsay_override(override):
        # type: (str) -> None
        assert Override(
            project_name=ProjectName("cowsay"), requirement=Requirement.parse(override)
        ) == Override.parse(override)

    assert_cowsay_override("cowsay")
    assert_cowsay_override("cowsay<6")
    assert_cowsay_override("cowsay==5.0")
    assert_cowsay_override("cowsay[tux]; python_version >= '3.5'")

    def assert_cowsay_replace(replacement):
        # type: (str) -> None
        assert Override(
            project_name=ProjectName("cowsay"), requirement=Requirement.parse(replacement)
        ) == Override.parse("cowsay={replacement}".format(replacement=replacement))

    assert_cowsay_replace("my-cowsay")
    assert_cowsay_replace("my-cowsay>2")
    assert_cowsay_replace("my-cowsay[foo, bar] >= 2; python_version == '3.11.*'")

    with pytest.raises(Override.InvalidError, match=r"Invalid override requirement '42!': "):
        Override.parse("42!")

    with pytest.raises(Override.InvalidError, match=r"Invalid override requirement '42!': "):
        Override.parse("cowsay=42!")


def test_override_str():
    # type: () -> None

    def assert_cowsay_override_str(override):
        # type: (str) -> None
        requirement = Requirement.parse(override)
        expected_str = str(requirement)
        assert expected_str == str(
            Override(project_name=ProjectName("cowsay"), requirement=requirement)
        )
        assert expected_str == str(Override.parse(override))

    assert_cowsay_override_str("cowsay")
    assert_cowsay_override_str("cowsay<6")
    assert_cowsay_override_str("cowsay[tux]<6; python_version < '3'")

    def assert_cowsay_replace_str(replacement):
        # type: (str) -> None
        requirement = Requirement.parse(replacement)
        expected_str = "cowsay={requirement}".format(requirement=requirement)
        assert expected_str == str(
            Override(project_name=ProjectName("cowsay"), requirement=requirement)
        )
        assert expected_str == str(
            Override.parse("cowsay={replacement}".format(replacement=replacement))
        )

    assert_cowsay_replace_str("my-cowsay")
    assert_cowsay_replace_str("my-cowsay>2")
    assert_cowsay_replace_str("my-cowsay[foo, bar] >= 2; python_version == '3.11.*'")


def test_create():
    # type: () -> None

    assert DependencyConfiguration() == DependencyConfiguration.create()
    assert DependencyConfiguration(
        excluded=(Requirement.parse("foo"), Requirement.parse("bar")),
        overridden={
            ProjectName("baz"): tuple([Requirement.parse("baz")]),
            ProjectName("spam"): tuple([Requirement.parse("spam")]),
            ProjectName("eggs"): tuple([Requirement.parse("green"), Requirement.parse("brown")]),
            ProjectName("fizz"): tuple([Requirement.parse("buzz")]),
        },
    ) == DependencyConfiguration.create(
        excluded=["foo", Requirement.parse("bar")],
        overridden=[
            "baz",
            Override(ProjectName("spam"), Requirement.parse("spam")),
            "eggs=green",
            Override.parse("fizz=buzz"),
            Override(ProjectName("eggs"), Requirement.parse("brown")),
        ],
    )
