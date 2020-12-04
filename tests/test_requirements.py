# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from textwrap import dedent

import pytest

from pex.common import safe_open, temporary_dir, touch
from pex.requirements import (
    Constraint,
    LogicalLine,
    ParseError,
    ReqInfo,
    Source,
    URLFetcher,
    parse_requirements,
)
from pex.testing import environment_as
from pex.third_party.packaging.markers import Marker
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Iterable, List, Optional, Union


@pytest.fixture
def chroot():
    # type: () -> Iterator[str]
    with temporary_dir() as chroot:
        curdir = os.getcwd()
        try:
            os.chdir(chroot)
            yield chroot
        finally:
            os.chdir(curdir)


def test_parse_requirements_failure_bad_include(chroot):
    req_iter = parse_requirements(Source.from_text("\n-r other-requirements.txt"))
    with pytest.raises(ParseError) as exc_info:
        next(req_iter)

    assert exc_info.value.logical_line == LogicalLine(
        raw_text="-r other-requirements.txt",
        processed_text="-r other-requirements.txt",
        source="<string>",
        start_line=2,
        end_line=2,
    )


def test_parse_requirements_failure_bad_requirement(chroot):
    # type: (str) -> None
    other_requirement_file = os.path.realpath(os.path.join(chroot, "other-requirements.txt"))
    with safe_open(other_requirement_file, "w") as fp:
        fp.write(
            dedent(
                """\
                GoodRequirement

                # A comment.
                AnotherRequirement

                # Another comment.
                BadRequirement\\
                [extra, another]; \\
                bad_marker == "2.7" \\
                    --global-option=foo # End of line comment.

                """
            )
        )

    req_iter = parse_requirements(Source.from_text("-r other-requirements.txt"))

    req_info = next(req_iter)
    assert isinstance(req_info, ReqInfo)
    assert "GoodRequirement" == req_info.project_name

    req_info = next(req_iter)
    assert isinstance(req_info, ReqInfo)
    assert "AnotherRequirement" == req_info.project_name

    with pytest.raises(ParseError) as exc_info:
        next(req_iter)

    assert exc_info.value.logical_line == LogicalLine(
        raw_text=(
            "BadRequirement\\\n"
            "[extra, another]; \\\n"
            'bad_marker == "2.7" \\\n'
            "    --global-option=foo # End of line comment.\n"
        ),
        processed_text='BadRequirement[extra, another]; bad_marker == "2.7" --global-option=foo',
        source=other_requirement_file,
        start_line=7,
        end_line=10,
    )


class MarkerWithEq(Marker):
    @classmethod
    def wrap(cls, marker):
        # type: (Optional[Marker]) -> Optional[MarkerWithEq]
        return None if marker is None else MarkerWithEq(str(marker))

    def __eq__(self, other):
        return type(other) == MarkerWithEq and str(self) == str(other)


def req(
    project_name=None,  # type: Optional[str]
    url=None,  # type: Optional[str]
    marker=None,  # type: Optional[str]
    editable=False,  # type: bool
    is_local_project=False,  # type: bool
):
    # type: (...) -> ReqInfo
    return ReqInfo(
        line=None,
        project_name=project_name,
        url=url,
        marker=MarkerWithEq.wrap(marker),
        editable=editable,
        is_local_project=is_local_project,
    )


def normalize_results(req_infos):
    # type: (Iterable[Union[Constraint, ReqInfo]]) -> List[Union[Constraint, ReqInfo]]
    def normalize_req_info(req_info):
        return req_info._replace(line=None)._replace(marker=MarkerWithEq.wrap(req_info.marker))

    return [
        normalize_req_info(req_info)
        if isinstance(req_info, ReqInfo)
        else Constraint(normalize_req_info(req_info.req_info))
        for req_info in req_infos
    ]


def test_parse_requirements_stress(chroot):
    # type: (str) -> None
    with safe_open(os.path.join(chroot, "other-requirements.txt"), "w") as fp:
        fp.write(
            # This includes both example snippets taken directly from
            # https://pip.pypa.io/en/stable/reference/pip_install/#requirements-file-format
            # not already covered by
            # https://pip.pypa.io/en/stable/reference/pip_install/#example-requirements-file.
            dedent(
                """\
                SomeProject
                SomeProject == 1.3
                SomeProject >=1.2,<2.0
                SomeProject[foo, bar]
                SomeProject~=1.4.2
                
                SomeProject ==5.4 ; python_version < '2.7'
                SomeProject; sys_platform == 'win32'
                
                SomeProject @ file:///somewhere/over/here
                
                FooProject >= 1.2 --global-option="--no-user-cfg" \\
                      --install-option="--prefix='/usr/local'" \\
                      --install-option="--no-compile"
                
                git+https://git.example.com/MyProject.git@da39a3ee5e6b4b0d3255bfef95601890afd80709#egg=MyProject
                git+ssh://git.example.com/MyProject#egg=MyProject
                git+file:///home/user/projects/MyProject#egg=MyProject&subdirectory=pkg_dir
                
                # N.B. This is not from the Pip docs unlike the examples above. We just want to 
                # chain in one more set of stress tests.
                -r extra/stress.txt
                """
            )
        )

    with safe_open(os.path.join(chroot, "extra", "stress.txt"), "w") as fp:
        fp.write(
            # These are tests of edge cases not included anywhere in the examples found in
            # https://pip.pypa.io/en/stable/reference/pip_install/#requirements-file-format.
            dedent(
                """\
                -c subdir/more-requirements.txt

                a/local/project[foo]; python_full_version == "2.7.8"
                ./another/local/project;python_version == "2.7.*"
                ./another/local/project
                ./
                # Local projects with basenames that are invalid Python project names (trailing _):
                tmp/tmpW8tdb_ 
                tmp/tmpW8tdb_[foo]
                tmp/tmpW8tdb_[foo];python_version == "3.9"

                hg+http://hg.example.com/MyProject@da39a3ee5e6b#egg=AnotherProject[extra,more];python_version=="3.9.*"&subdirectory=foo/bar

                ftp://a/${PROJECT_NAME}-1.0.tar.gz
                http://a/${PROJECT_NAME}-1.0.zip
                https://a/numpy-1.9.2-cp34-none-win32.whl

                Django@ git+https://github.com/django/django.git
                Django@git+https://github.com/django/django.git@stable/2.1.x
                Django@ git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8
                """
            )
        )
    touch("extra/pyproject.toml")
    touch("extra/a/local/project/pyproject.toml")
    touch("extra/another/local/project/setup.py")
    touch("extra/tmp/tmpW8tdb_/setup.py")

    with safe_open(os.path.join(chroot, "subdir", "more-requirements.txt"), "w") as fp:
        fp.write(
            # This checks requirements (`ReqInfo`s) are wrapped up into `Constraints`.
            dedent(
                """\
                AnotherProject
                """
            )
        )

    req_iter = parse_requirements(
        Source.from_text(
            # N.B.: Taken verbatim from:
            #   https://pip.pypa.io/en/stable/reference/pip_install/#example-requirements-file
            dedent(
                """\
                #
                ####### example-requirements.txt #######
                #
                ###### Requirements without Version Specifiers ######
                nose
                nose-cov
                beautifulsoup4
                #
                ###### Requirements with Version Specifiers ######
                #   See https://www.python.org/dev/peps/pep-0440/#version-specifiers
                docopt == 0.6.1             # Version Matching. Must be version 0.6.1
                keyring >= 4.1.1            # Minimum version 4.1.1
                coverage != 3.5             # Version Exclusion. Anything except version 3.5
                Mopidy-Dirble ~= 1.1        # Compatible release. Same as >= 1.1, == 1.*
                #
                ###### Refer to other requirements files ######
                -r other-requirements.txt
                #
                #
                ###### A particular file ######
                ./downloads/numpy-1.9.2-cp34-none-win32.whl
                http://wxpython.org/Phoenix/snapshot-builds/wxPython_Phoenix-3.0.3.dev1820+49a8884-cp34-none-win_amd64.whl
                #
                ###### Additional Requirements without Version Specifiers ######
                #   Same as 1st section, just here to show that you can put things in any order.
                rejected
                green
                #
                """
            ),
        )
    )
    touch("downloads/numpy-1.9.2-cp34-none-win32.whl")
    with environment_as(PROJECT_NAME="Project"):
        results = normalize_results(req_iter)

    assert [
        req(project_name="nose"),
        req(project_name="nose-cov"),
        req(project_name="beautifulsoup4"),
        req(project_name="docopt"),
        req(project_name="keyring"),
        req(project_name="coverage"),
        req(project_name="Mopidy-Dirble"),
        req(project_name="SomeProject"),
        req(project_name="SomeProject"),
        req(project_name="SomeProject"),
        req(project_name="SomeProject"),
        req(project_name="SomeProject"),
        req(project_name="SomeProject", marker="python_version < '2.7'"),
        req(project_name="SomeProject", marker="sys_platform == 'win32'"),
        req(project_name="SomeProject", url="file:///somewhere/over/here"),
        req(project_name="FooProject"),
        req(
            project_name="MyProject",
            url="git+https://git.example.com/MyProject.git@da39a3ee5e6b4b0d3255bfef95601890afd80709",
        ),
        req(project_name="MyProject", url="git+ssh://git.example.com/MyProject"),
        req(project_name="MyProject", url="git+file:/home/user/projects/MyProject"),
        Constraint(req(project_name="AnotherProject")),
        req(
            url=os.path.realpath("extra/a/local/project"),
            marker="python_full_version == '2.7.8'",
            is_local_project=True,
        ),
        req(
            url=os.path.realpath("extra/another/local/project"),
            marker="python_version == '2.7.*'",
            is_local_project=True,
        ),
        req(url=os.path.realpath("extra/another/local/project"), is_local_project=True),
        req(url=os.path.realpath("extra"), is_local_project=True),
        req(url=os.path.realpath("extra/tmp/tmpW8tdb_"), is_local_project=True),
        req(url=os.path.realpath("extra/tmp/tmpW8tdb_"), is_local_project=True),
        req(
            url=os.path.realpath("extra/tmp/tmpW8tdb_"),
            marker="python_version == '3.9'",
            is_local_project=True,
        ),
        req(
            project_name="AnotherProject",
            url="hg+http://hg.example.com/MyProject@da39a3ee5e6b",
            marker="python_version == '3.9.*'",
        ),
        req(project_name="Project", url="ftp://a/Project-1.0.tar.gz"),
        req(project_name="Project", url="http://a/Project-1.0.zip"),
        req(project_name="numpy", url="https://a/numpy-1.9.2-cp34-none-win32.whl"),
        req(project_name="Django", url="git+https://github.com/django/django.git"),
        req(project_name="Django", url="git+https://github.com/django/django.git@stable/2.1.x"),
        req(
            project_name="Django",
            url="git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8",
        ),
        req(
            project_name="numpy",
            url=os.path.realpath("./downloads/numpy-1.9.2-cp34-none-win32.whl"),
        ),
        req(
            project_name="wxPython_Phoenix",
            url="http://wxpython.org/Phoenix/snapshot-builds/wxPython_Phoenix-3.0.3.dev1820+49a8884-cp34-none-win_amd64.whl",
        ),
        req(project_name="rejected"),
        req(project_name="green"),
    ] == results


def test_parse_requirements_from_url():
    # type: () -> None
    req_iter = parse_requirements(
        Source.from_text(
            "-r https://raw.githubusercontent.com/pantsbuild/example-python/c6052498f25a436f2639ccd0bc846cec1a55d7d5/requirements.txt"
        ),
        fetcher=URLFetcher(),
    )
    results = normalize_results(req_iter)
    assert [
        req(project_name="ansicolors"),
        req(project_name="setuptools"),
        req(project_name="translate"),
        req(project_name="protobuf"),
    ] == results


def test_parse_requirements_from_url_no_fetcher():
    # type: () -> None
    req_iter = parse_requirements(
        Source.from_text(
            "-r https://raw.githubusercontent.com/pantsbuild/example-python/c6052498f25a436f2639ccd0bc846cec1a55d7d5/requirements.txt"
        )
    )
    with pytest.raises(ParseError) as exec_info:
        next(req_iter)

    assert (
        "<string> line 1:\n"
        "-r https://raw.githubusercontent.com/pantsbuild/example-python/c6052498f25a436f2639ccd0bc846cec1a55d7d5/requirements.txt\n"
        "Problem resolving requirements file: The source is a url but no fetcher was supplied to resolve its contents with."
    ) == str(exec_info.value)
