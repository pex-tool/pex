# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import sys
from argparse import ArgumentParser, Namespace
from textwrap import dedent
from typing import List, Optional, Sequence

import pytest

from pex.common import safe_open
from pex.dist_metadata import Requirement
from pex.resolve import project
from pex.typing import cast
from testing import pushd
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

            # Per the spec, parsing should be lazy; so we should never "see" the bogus 
            # `set-phasers-to` inline table element.
            bar = [{set-phasers-to = "stun"}]
            
            bad-req = ["meaning-of-life=42"]
            missing-include = [{include-group = "does-not-exist"}]
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


def parse_args(
    args,  # type: Sequence[str]
    cwd=None,  # type: Optional[str]
):
    # type: (...) -> Namespace
    with pushd(cwd or os.getcwd()):
        parser = ArgumentParser()
        project.register_options(parser, project_help="test")
        return parser.parse_args(args=args)


def parse_groups(
    args,  # type: Sequence[str]
    cwd=None,  # type: Optional[str]
):
    # type: (...) -> List[Requirement]
    return list(project.get_group_requirements(parse_args(args, cwd=cwd)))


req = Requirement.parse


def test_nominal(project_dir1):
    # type: (str) -> None
    expected_reqs = [req("foo"), req("bar>2")]
    assert expected_reqs == parse_groups(
        ["--group", "basic@{project_dir}".format(project_dir=project_dir1)]
    )
    assert expected_reqs == parse_groups(["--group", "basic"], cwd=project_dir1)


def test_include(project_dir1):
    # type: (str) -> None
    expected_reqs = [req("foo"), req("bar>2")]
    assert expected_reqs == parse_groups(
        ["--group", "include1@{project_dir}".format(project_dir=project_dir1)]
    )
    assert expected_reqs == parse_groups(["--group", "include1"], cwd=project_dir1)


def test_include_multi(project_dir1):
    # type: (str) -> None
    expected_reqs = [req("spam"), req("foo"), req("bar>2"), req("bar")]
    assert expected_reqs == parse_groups(
        ["--group", "include2@{project_dir}".format(project_dir=project_dir1)]
    )
    assert expected_reqs == parse_groups(["--group", "include2@."], cwd=project_dir1)


def test_multiple_projects(
    project_dir1,  # type: str
    project_dir2,  # type: str
):
    # type: (...) -> None
    expected_reqs = [
        req("foo"),
        req("bar>2"),
        req("baz<3; python_version < '3.9'"),
        req("baz; python_version >= '3.9'"),
    ]
    assert expected_reqs == parse_groups(
        [
            "--group",
            "include1@{project_dir}".format(project_dir=project_dir1),
            "--group",
            "basic@{project_dir}".format(project_dir=project_dir2),
            "--group",
            "basic@{project_dir}".format(project_dir=project_dir1),
        ]
    )
    assert expected_reqs == parse_groups(
        [
            "--group",
            "include1",
            "--group",
            "basic@{project_dir}".format(project_dir=project_dir2),
            "--group",
            "basic@",
        ],
        cwd=project_dir1,
    )


def test_missing_group(project_dir1):
    # type: (str) -> None

    with pytest.raises(
        KeyError,
        match=re.escape(
            "The dependency group 'does-not-exist' specified by 'does-not-exist@{project}' does "
            "not exist in {project}".format(project=project_dir1)
        ),
    ):
        parse_args(["--group", "does-not-exist@{project}".format(project=project_dir1)])


def test_invalid_group_bad_req(project_dir1):
    # type: (str) -> None

    options = parse_args(["--group", "bad-req"], cwd=project_dir1)
    with pytest.raises(
        ValueError,
        match=re.escape(
            "Invalid [dependency-group] entry 'bad-req'.\n"
            "Item 1: 'meaning-of-life=42', is an invalid dependency specifier: Expected end or "
            "semicolon (after name and no valid version specifier)\n"
            "    meaning-of-life=42\n"
            "                   ^"
        ),
    ):
        project.get_group_requirements(options)


def test_invalid_group_bad_inline_table(project_dir1):
    # type: (str) -> None

    options = parse_args(["--group", "bar"], cwd=project_dir1)
    with pytest.raises(
        ValueError,
        match=re.escape(
            "Invalid [dependency-group] entry 'bar'.\n"
            "Item 1 is a non 'include-group' table and only dependency specifiers and single entry "
            "'include-group' tables are allowed in group dependency lists.\n"
            "See https://peps.python.org/pep-0735/#specification for the specification of "
            "[dependency-groups] syntax.\n"
            "Given: {'set-phasers-to': 'stun'}"
        ),
    ):
        project.get_group_requirements(options)


def test_invalid_group_missing_include(project_dir1):
    # type: (str) -> None

    options = parse_args(["--group", "missing-include"], cwd=project_dir1)
    with pytest.raises(
        KeyError,
        match=re.escape(
            "The dependency group 'does-not-exist' required by dependency group 'missing-include' "
            "does not exist in the project at {project}.".format(project=project_dir1)
        ),
    ):
        project.get_group_requirements(options)
