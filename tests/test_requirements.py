# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from textwrap import dedent

import pytest

from pex.common import safe_open, temporary_dir, touch
from pex.requirements import (
    Constraint,
    LocalProjectRequirement,
    LogicalLine,
    ParseError,
    PyPIRequirement,
    Source,
    URLFetcher,
    URLRequirement,
    parse_requirement_file,
    parse_requirement_from_project_name_and_specifier,
    parse_requirements,
)
from pex.testing import environment_as
from pex.third_party.packaging.markers import Marker
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, List, Optional, Union

    from pex.requirements import ParsedRequirement

    ParsedRequirementOrConstraint = Union[ParsedRequirement, Constraint]


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

    parsed_requirement = next(req_iter)
    assert isinstance(parsed_requirement, PyPIRequirement)
    assert "GoodRequirement" == parsed_requirement.requirement.project_name

    parsed_requirement = next(req_iter)
    assert isinstance(parsed_requirement, PyPIRequirement)
    assert "AnotherRequirement" == parsed_requirement.requirement.project_name

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


DUMMY_LINE = LogicalLine("", "", "<string>", 1, 1)


def req(
    project_name,  # type: str
    extras=None,  # type: Optional[Iterable[str]]
    specifier=None,  # type: Optional[str]
    marker=None,  # type: Optional[str]
    editable=False,  # type: bool
):
    # type: (...) -> PyPIRequirement
    return PyPIRequirement.create(
        line=DUMMY_LINE,
        requirement=parse_requirement_from_project_name_and_specifier(
            project_name, extras=extras, specifier=specifier, marker=marker
        ),
        editable=editable,
    )


def url_req(
    url,  # type: str
    project_name,  # type: str
    extras=None,  # type: Optional[Iterable[str]]
    specifier=None,  # type: Optional[str]
    marker=None,  # type: Optional[str]
    editable=False,  # type: bool
):
    # type: (...) -> URLRequirement
    return URLRequirement.create(
        line=DUMMY_LINE,
        url=url,
        requirement=parse_requirement_from_project_name_and_specifier(
            project_name, extras=extras, specifier=specifier, marker=marker
        ),
        editable=editable,
    )


def local_req(
    path,  # type: str
    extras=None,  # type: Optional[Iterable[str]]
    marker=None,  # type: Optional[str]
    editable=False,  # type: bool
):
    # type: (...) -> LocalProjectRequirement
    return LocalProjectRequirement.create(
        line=DUMMY_LINE,
        path=path,
        extras=extras,
        marker=MarkerWithEq.wrap(marker),
        editable=editable,
    )


def normalize_results(parsed_requirements):
    # type: (Iterable[ParsedRequirementOrConstraint]) -> List[ParsedRequirementOrConstraint]
    return [
        parsed_requirement._replace(
            line=DUMMY_LINE, marker=MarkerWithEq.wrap(parsed_requirement.marker)
        )
        if isinstance(parsed_requirement, LocalProjectRequirement)
        else parsed_requirement._replace(line=DUMMY_LINE)
        for parsed_requirement in parsed_requirements
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
                
                SomeProject @ https://example.com/somewhere/over/here
                SomeProject @ file:somewhere/over/here
                
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
    touch("somewhere/over/here/pyproject.toml")

    with safe_open(os.path.join(chroot, "extra", "stress.txt"), "w") as fp:
        fp.write(
            # These are tests of edge cases not included anywhere in the examples found in
            # https://pip.pypa.io/en/stable/reference/pip_install/#requirements-file-format.
            dedent(
                """\
                -c file:subdir/more-requirements.txt

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
                Django @ file:projects/django-2.3.zip; python_version >= "3.10"
                """
            )
        )
    touch("extra/pyproject.toml")
    touch("extra/a/local/project/pyproject.toml")
    touch("extra/another/local/project/setup.py")
    touch("extra/tmp/tmpW8tdb_/setup.py")
    touch("extra/projects/django-2.3.zip")

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
        req(project_name="docopt", specifier="==0.6.1"),
        req(project_name="keyring", specifier=">=4.1.1"),
        req(project_name="coverage", specifier="!=3.5"),
        req(project_name="Mopidy-Dirble", specifier="~=1.1"),
        req(project_name="SomeProject"),
        req(project_name="SomeProject", specifier="==1.3"),
        req(project_name="SomeProject", specifier=">=1.2,<2.0"),
        req(project_name="SomeProject", extras=["foo", "bar"]),
        req(project_name="SomeProject", specifier="~=1.4.2"),
        req(project_name="SomeProject", specifier="==5.4", marker="python_version < '2.7'"),
        req(project_name="SomeProject", marker="sys_platform == 'win32'"),
        url_req(project_name="SomeProject", url="https://example.com/somewhere/over/here"),
        local_req(path=os.path.realpath("somewhere/over/here")),
        req(project_name="FooProject", specifier=">=1.2"),
        url_req(
            project_name="MyProject",
            url="git+https://git.example.com/MyProject.git@da39a3ee5e6b4b0d3255bfef95601890afd80709",
        ),
        url_req(project_name="MyProject", url="git+ssh://git.example.com/MyProject"),
        url_req(project_name="MyProject", url="git+file:/home/user/projects/MyProject"),
        Constraint(DUMMY_LINE, Requirement.parse("AnotherProject")),
        local_req(
            path=os.path.realpath("extra/a/local/project"),
            extras=["foo"],
            marker="python_full_version == '2.7.8'",
        ),
        local_req(
            path=os.path.realpath("extra/another/local/project"),
            marker="python_version == '2.7.*'",
        ),
        local_req(path=os.path.realpath("extra/another/local/project")),
        local_req(path=os.path.realpath("extra")),
        local_req(path=os.path.realpath("extra/tmp/tmpW8tdb_")),
        local_req(path=os.path.realpath("extra/tmp/tmpW8tdb_"), extras=["foo"]),
        local_req(
            path=os.path.realpath("extra/tmp/tmpW8tdb_"),
            extras=["foo"],
            marker="python_version == '3.9'",
        ),
        url_req(
            project_name="AnotherProject",
            url="hg+http://hg.example.com/MyProject@da39a3ee5e6b",
            extras=["more", "extra"],
            marker="python_version == '3.9.*'",
        ),
        url_req(project_name="Project", url="ftp://a/Project-1.0.tar.gz", specifier="==1.0"),
        url_req(project_name="Project", url="http://a/Project-1.0.zip", specifier="==1.0"),
        url_req(
            project_name="numpy",
            url="https://a/numpy-1.9.2-cp34-none-win32.whl",
            specifier="==1.9.2",
        ),
        url_req(project_name="Django", url="git+https://github.com/django/django.git"),
        url_req(project_name="Django", url="git+https://github.com/django/django.git@stable/2.1.x"),
        url_req(
            project_name="Django",
            url="git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8",
        ),
        url_req(
            project_name="Django",
            url=os.path.realpath("extra/projects/django-2.3.zip"),
            specifier="==2.3",
            marker="python_version>='3.10'",
        ),
        url_req(
            project_name="numpy",
            url=os.path.realpath("./downloads/numpy-1.9.2-cp34-none-win32.whl"),
            specifier="==1.9.2",
        ),
        url_req(
            project_name="wxPython_Phoenix",
            url="http://wxpython.org/Phoenix/snapshot-builds/wxPython_Phoenix-3.0.3.dev1820+49a8884-cp34-none-win_amd64.whl",
            specifier="==3.0.3.dev1820+49a8884",
        ),
        req(project_name="rejected"),
        req(project_name="green"),
    ] == results


EXAMPLE_PYTHON_REQUIREMENTS_URL = (
    "https://raw.githubusercontent.com/pantsbuild/example-python/"
    "c6052498f25a436f2639ccd0bc846cec1a55d7d5"
    "/requirements.txt"
)

EXPECTED_EXAMPLE_PYTHON_REQ_INFOS = [
    req(project_name="ansicolors", specifier=">=1.0.2"),
    req(project_name="setuptools", specifier=">=42.0.0"),
    req(project_name="translate", specifier=">=3.2.1"),
    req(project_name="protobuf", specifier=">=3.11.3"),
]


def test_parse_requirements_from_url():
    # type: () -> None
    req_iter = parse_requirements(
        Source.from_text("-r {}".format(EXAMPLE_PYTHON_REQUIREMENTS_URL)),
        fetcher=URLFetcher(),
    )
    results = normalize_results(req_iter)
    assert EXPECTED_EXAMPLE_PYTHON_REQ_INFOS == results


def test_parse_constraints_from_url():
    # type: () -> None
    req_iter = parse_requirements(
        Source.from_text("-c {}".format(EXAMPLE_PYTHON_REQUIREMENTS_URL)),
        fetcher=URLFetcher(),
    )
    results = normalize_results(req_iter)
    assert [
        Constraint(req.line, req.requirement) for req in EXPECTED_EXAMPLE_PYTHON_REQ_INFOS
    ] == results


def test_parse_requirement_file_from_url():
    # type: () -> None
    req_iter = parse_requirement_file(EXAMPLE_PYTHON_REQUIREMENTS_URL, fetcher=URLFetcher())
    results = normalize_results(req_iter)
    assert EXPECTED_EXAMPLE_PYTHON_REQ_INFOS == results


def test_parse_requirement_file_from_file_url(tmpdir):
    # type: (Any) -> None
    requirements_file = os.path.join(str(tmpdir), "requirements.txt")
    with open(requirements_file, "w") as fp:
        fp.write(
            dedent(
                """\
                foo==1.0.0
                bar>3
                """
            )
        )

    req_iter = parse_requirement_file(requirements_file)
    expected = normalize_results(req_iter)

    req_iter = parse_requirement_file("file:{}".format(requirements_file))
    results = normalize_results(req_iter)
    assert expected == results
    req_iter = parse_requirement_file("file://{}".format(requirements_file))
    results = normalize_results(req_iter)
    assert expected == results


def test_parse_requirements_from_url_no_fetcher():
    # type: () -> None
    req_iter = parse_requirements(Source.from_text("-r {}".format(EXAMPLE_PYTHON_REQUIREMENTS_URL)))
    with pytest.raises(ParseError) as exec_info:
        next(req_iter)

    assert (
        "<string> line 1:\n"
        "-r {}\n"
        "Problem resolving requirements file: The source is a url but no fetcher was supplied to "
        "resolve its contents with.".format(EXAMPLE_PYTHON_REQUIREMENTS_URL)
    ) == str(exec_info.value)
