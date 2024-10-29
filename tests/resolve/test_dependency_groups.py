# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import sys
from argparse import ArgumentParser, Namespace
from textwrap import dedent
from typing import List

import pytest

from pex.common import safe_open
from pex.dist_metadata import Requirement
from pex.resolve import project
from pex.typing import cast
from testing.pytest.tmp import Tempdir


def create_dependency_groups_project(
    pyproject_toml_path,  # type: str
    contents,  # type: str
):
    # type: (...) -> str
    with safe_open(pyproject_toml_path, "w") as fp:
        fp.write(contents)
        return cast(str, os.path.dirname(fp.name))


@pytest.fixture
def project_dir1(tmpdir):
    # type: (Tempdir) -> str
    if sys.version_info[:2] < (3, 7):
        pytest.skip("The toml library we use for old pythons cannot parse heterogeneous lists.")

    return create_dependency_groups_project(
        tmpdir.join("project1", "pyproject.toml"),
        dedent(
            """\
            [dependency-groups]
            basic = ["foo", "bar>2"]
            include1 = [{include-group = "basic"}]
            include2 = ["spam", {include-group = "include1"}, "bar", "foo"]
            """
        ),
    )


@pytest.fixture
def project_dir2(tmpdir):
    # type: (Tempdir) -> str
    return create_dependency_groups_project(
        tmpdir.join("project2", "pyproject.toml"),
        dedent(
            """\
            [dependency-groups]
            basic = [
                "baz<3; python_version < '3.9'",
                "baz; python_version >= '3.9'",
            ]
            """
        ),
    )


def parse_args(*args):
    # type: (*str) -> Namespace
    parser = ArgumentParser()
    project.register_options(parser, project_help="test")
    return parser.parse_args(args=args)


def parse_groups(*args):
    # type: (*str) -> List[Requirement]
    return list(project.get_group_requirements(parse_args(*args)))


req = Requirement.parse


def test_nominal(project_dir1):
    # type: (str) -> None
    assert [req("foo"), req("bar>2")] == parse_groups(
        "--group", "basic@{project_dir}".format(project_dir=project_dir1)
    )


def test_include(project_dir1):
    # type: (str) -> None
    assert [req("foo"), req("bar>2")] == parse_groups(
        "--group", "include1@{project_dir}".format(project_dir=project_dir1)
    )


def test_include_multi(project_dir1):
    # type: (str) -> None
    assert [req("spam"), req("foo"), req("bar>2"), req("bar")] == parse_groups(
        "--group", "include2@{project_dir}".format(project_dir=project_dir1)
    )


def test_multiple_projects(
    project_dir1,  # type: str
    project_dir2,  # type: str
):
    # type: (...) -> None
    assert [
        req("foo"),
        req("bar>2"),
        req("baz<3; python_version < '3.9'"),
        req("baz; python_version >= '3.9'"),
    ] == parse_groups(
        "--group",
        "include1@{project_dir}".format(project_dir=project_dir1),
        "--group",
        "basic@{project_dir}".format(project_dir=project_dir2),
        "--group",
        "basic@{project_dir}".format(project_dir=project_dir1),
    )
