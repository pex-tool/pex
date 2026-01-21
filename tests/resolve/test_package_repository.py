# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.pep_503 import ProjectName
from pex.resolve.package_repository import Scope
from pex.third_party.packaging.markers import Marker


def assert_project_name(value):
    # type: (str) -> Scope
    scope = Scope.parse(value)
    assert isinstance(scope.project, ProjectName)
    return scope


def assert_project_re(value):
    # type: (str) -> Scope
    scope = Scope.parse(value)
    assert (
        scope.project
        and not isinstance(scope.project, ProjectName)
        and hasattr(scope.project, "match")
    )
    return scope


def assert_marker(
    expected,  # type: str
    actual,  # type: Marker
):
    # type: (...) -> None
    # N.B.: Older versions of Marker do not implement __eq__; so we use str(...) as a proxy.
    assert str(Marker(expected)) == str(actual)


def test_parse():
    # type: () -> None

    scope = assert_project_name("foo")
    assert scope.marker is None

    scope = assert_project_name("foo; python_version == '3.9'")
    assert_marker("python_version == '3.9'", scope.marker)

    scope = assert_project_re("^(foo|bar|baz)$")
    assert scope.marker is None

    scope = assert_project_re("^(foo|bar|baz)$; python_version == '3.9'")
    assert_marker("python_version == '3.9'", scope.marker)

    scope = Scope.parse("python_version == '3.9'")
    assert scope.project is None
    assert_marker("python_version == '3.9'", scope.marker)


@pytest.mark.parametrize(
    "scope",
    [
        pytest.param(Scope.parse(scope), id=scope)
        for scope in (
            "foo",
            "foo; python_version == '3.9'",
            "^(foo|bar|baz)$",
            "^(foo|bar|baz)$; python_version == '3.9'",
            "python_version == '3.9'",
        )
    ],
)
def test_parse_str_round_trip(scope):
    # type: (Scope) -> None

    assert scope == Scope.parse(str(scope))


def test_in_scope():
    # type: () -> None

    assert Scope.parse("foo").in_scope({})
    assert Scope.parse("foo").in_scope({"python_version": "3.9"})
    assert Scope.parse("foo").in_scope({}, project_name=ProjectName("Foo"))
    assert Scope.parse("foo").in_scope({"python_version": "3.9"}, project_name=ProjectName("Foo"))

    assert Scope.parse("^f.*").in_scope({}, project_name=ProjectName("Foo"))
    assert Scope.parse("^f.*").in_scope({"python_version": "3.9"}, project_name=ProjectName("Foo"))

    assert Scope.parse("^f.*; python_version == '3.9'").in_scope(
        {"python_version": "3.9"}, project_name=ProjectName("Foo")
    )
    assert not Scope.parse("^f.*; python_version == '3.9'").in_scope(
        {"python_version": "3.10"}, project_name=ProjectName("Foo")
    )

    assert Scope.parse("python_version == '3.9'").in_scope(
        {"python_version": "3.9"}, project_name=ProjectName("foo")
    )
