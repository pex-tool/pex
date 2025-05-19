# Copyright 2020 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from textwrap import dedent

import pytest

from pex.artifact_url import VCS, ArtifactURL
from pex.common import environment_as, safe_open, touch
from pex.compatibility import urlparse
from pex.dist_metadata import Requirement
from pex.fetcher import URLFetcher
from pex.requirements import (
    Constraint,
    LocalProjectRequirement,
    LogicalLine,
    ParseError,
    PyPIRequirement,
    Source,
    URLRequirement,
    VCSRequirement,
    parse_requirement_file,
    parse_requirement_from_project_name_and_specifier,
    parse_requirements,
)
from pex.third_party.packaging.markers import Marker
from pex.typing import TYPE_CHECKING
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, Iterable, List, Optional, Union

    import attr  # vendor:skip

    from pex.requirements import ParsedRequirement

    ParsedRequirementOrConstraint = Union[ParsedRequirement, Constraint]
else:
    from pex.third_party import attr


def test_parse_requirements_failure_bad_include(tmpdir):
    # type: (Tempdir) -> None

    # N.B.: This test assumes there is no `other-requirements.txt` in the root of the Pex repo,
    # which is the cwd of the test runner.
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


def test_parse_requirements_failure_bad_requirement(tmpdir):
    # type: (Tempdir) -> None
    other_requirement_file = tmpdir.join("other-requirements.txt")
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

    req_iter = parse_requirements(
        Source.from_text("-r {requirements_txt}".format(requirements_txt=other_requirement_file))
    )

    parsed_requirement = next(req_iter)
    assert isinstance(parsed_requirement, PyPIRequirement)
    assert "GoodRequirement" == parsed_requirement.requirement.name

    parsed_requirement = next(req_iter)
    assert isinstance(parsed_requirement, PyPIRequirement)
    assert "AnotherRequirement" == parsed_requirement.requirement.name

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
):
    # type: (...) -> PyPIRequirement
    return PyPIRequirement(
        line=DUMMY_LINE,
        requirement=parse_requirement_from_project_name_and_specifier(
            project_name, extras=extras, specifier=specifier, marker=marker
        ),
    )


def file_req(
    url,  # type: str
    project_name,  # type: str
    extras=None,  # type: Optional[Iterable[str]]
    specifier=None,  # type: Optional[str]
    marker=None,  # type: Optional[str]
):
    # type: (...) -> URLRequirement
    return URLRequirement(
        line=DUMMY_LINE,
        url=ArtifactURL.parse(url),
        requirement=parse_requirement_from_project_name_and_specifier(
            project_name, extras=extras, specifier=specifier, marker=marker
        ),
    )


def url_req(
    url,  # type: str
    project_name,  # type: str
    extras=None,  # type: Optional[Iterable[str]]
    specifier=None,  # type: Optional[str]
    marker=None,  # type: Optional[str]
):
    # type: (...) -> URLRequirement
    return URLRequirement(
        line=DUMMY_LINE,
        url=ArtifactURL.parse(url),
        requirement=parse_requirement_from_project_name_and_specifier(
            project_name, extras=extras, specifier=specifier, marker=marker, url=url
        ),
    )


def vcs_req(
    vcs,  # type: VCS.Value
    url,  # type: str
    project_name,  # type: str
    extras=None,  # type: Optional[Iterable[str]]
    specifier=None,  # type: Optional[str]
    marker=None,  # type: Optional[str]
):
    # type: (...) -> VCSRequirement

    url_info = urlparse.urlparse(url)
    return VCSRequirement(
        line=DUMMY_LINE,
        vcs=vcs,
        url=url,
        requirement=parse_requirement_from_project_name_and_specifier(
            project_name,
            extras=extras,
            specifier=specifier,
            marker=marker,
            url=url_info._replace(
                scheme="{vcs}+{scheme}".format(vcs=vcs, scheme=url_info.scheme)
            ).geturl(),
        ),
    )


def local_req(
    path,  # type: str
    extras=None,  # type: Optional[Iterable[str]]
    marker=None,  # type: Optional[str]
    editable=False,  # type: bool
):
    # type: (...) -> LocalProjectRequirement
    return LocalProjectRequirement(
        line=DUMMY_LINE,
        path=path,
        extras=extras,
        marker=MarkerWithEq.wrap(marker),
        editable=editable,
    )


def normalize_results(parsed_requirements):
    # type: (Iterable[ParsedRequirementOrConstraint]) -> List[ParsedRequirementOrConstraint]
    return [
        attr.evolve(
            parsed_requirement, line=DUMMY_LINE, marker=MarkerWithEq.wrap(parsed_requirement.marker)
        )
        if isinstance(parsed_requirement, LocalProjectRequirement)
        else attr.evolve(parsed_requirement, line=DUMMY_LINE)
        for parsed_requirement in parsed_requirements
    ]


def test_parse_requirements_stress(tmpdir):
    # type: (Tempdir) -> None
    other_requirements_txt = tmpdir.join("other-requirements.txt")
    with safe_open(other_requirements_txt, "w") as fp:
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
    touch(tmpdir.join("somewhere", "over", "here", "pyproject.toml"))

    with safe_open(tmpdir.join("extra", "stress.txt"), "w") as fp:
        fp.write(
            # These are tests of edge cases not included anywhere in the examples found in
            # https://pip.pypa.io/en/stable/reference/pip_install/#requirements-file-format.
            dedent(
                """\
                -c file:subdir/more-requirements.txt

                a/local/project[foo]; python_full_version == "2.7.8"
                ./another/local/project;python_version == "2.7.*"
                ./another/local/project ; python_version == "2.7.*"
                ./another/local/project
                ./
                # Local projects with basenames that are invalid Python project names (trailing _):
                tmp/tmpW8tdb_ 
                tmp/tmpW8tdb_[foo]
                tmp/tmpW8tdb_[foo];python_version == "3.9"

                hg+http://hg.example.com/MyProject@da39a3ee5e6b\\
                    #egg=AnotherProject[extra,more];python_version=="3.9.*"&subdirectory=foo/bar
                hg+http://hg.example.com/MyProject@da39a3ee5e6b\\
                    #egg=AnotherProject[extra,more] ; python_version=="3.9.*"&subdirectory=foo/bar

                ftp://a/${{PROJECT_NAME}}-1.0.tar.gz
                http://a/${{PROJECT_NAME}}-1.0.zip
                https://a/numpy-1.9.2-cp34-none-win32.whl
                https://a/numpy-1.9.2-cp34-none-win32.whl;\\
                    python_version=="3.4.*" and sys_platform=='win32'
                https://a/numpy-1.9.2-cp34-none-win32.whl ; \\
                    python_version=="3.4.*" and sys_platform=='win32'

                Django@ git+https://github.com/django/django.git
                Django@git+https://github.com/django/django.git@stable/2.1.x
                Django@ git+https://github.com/django/django.git\\
                    @fd209f62f1d83233cc634443cfac5ee4328d98b8
                Django @ file:projects/django-2.3.zip; python_version >= "3.10"
                Django @ file:projects/django-2.3.zip ;python_version >= "3.10"

                # Wheel with local version
                http://download.pytorch.org/whl/cpu/torch-1.12.1%2Bcpu-cp310-cp310-linux_x86_64.whl

                # Editable
                -e file://{chroot}/extra/a/local/project
                --editable file://{chroot}/extra/a/local/project/
                -e ./another/local/project
                --editable ./another/local/project/
                """
            ).format(chroot=tmpdir)
        )
    touch(tmpdir.join("extra", "pyproject.toml"))
    touch(tmpdir.join("extra", "a", "local", "project", "pyproject.toml"))
    touch(tmpdir.join("extra", "another", "local", "project", "setup.py"))
    touch(tmpdir.join("extra", "tmp", "tmpW8tdb_", "setup.py"))
    touch(tmpdir.join("extra", "projects", "django-2.3.zip"))

    with safe_open(tmpdir.join("extra", "subdir", "more-requirements.txt"), "w") as fp:
        fp.write(
            # This checks requirements (`ReqInfo`s) are wrapped up into `Constraints`.
            dedent(
                """\
                AnotherProject
                """
            )
        )

    root_requirements_txt = tmpdir.join("requirements.txt")
    with safe_open(root_requirements_txt, "w") as fp:
        fp.write(
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
                #   See https://peps.python.org/pep-0440/#version-specifiers
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
            )
        )
    req_iter = parse_requirement_file(root_requirements_txt)

    # Ensure local non-distribution files matching distribution names are not erroneously probed
    # as distributions to find name and version metadata.
    touch(tmpdir.join("nose"))

    touch(tmpdir.join("downloads", "numpy-1.9.2-cp34-none-win32.whl"))
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
        local_req(path=tmpdir.join("somewhere", "over", "here")),
        req(project_name="FooProject", specifier=">=1.2"),
        vcs_req(
            vcs=VCS.Git,
            project_name="MyProject",
            url="https://git.example.com/MyProject.git@da39a3ee5e6b4b0d3255bfef95601890afd80709",
        ),
        vcs_req(vcs=VCS.Git, project_name="MyProject", url="ssh://git.example.com/MyProject"),
        vcs_req(
            vcs=VCS.Git,
            project_name="MyProject",
            url="file:///home/user/projects/MyProject#subdirectory=pkg_dir",
        ),
        Constraint(DUMMY_LINE, Requirement.parse("AnotherProject")),
        local_req(
            path=tmpdir.join("extra", "a", "local", "project"),
            extras=["foo"],
            marker="python_full_version == '2.7.8'",
        ),
        local_req(
            path=tmpdir.join("extra", "another", "local", "project"),
            marker="python_version == '2.7.*'",
        ),
        local_req(
            path=tmpdir.join("extra", "another", "local", "project"),
            marker="python_version == '2.7.*'",
        ),
        local_req(path=tmpdir.join("extra", "another", "local", "project")),
        local_req(path=tmpdir.join("extra")),
        local_req(path=tmpdir.join("extra", "tmp", "tmpW8tdb_")),
        local_req(path=tmpdir.join("extra", "tmp", "tmpW8tdb_"), extras=["foo"]),
        local_req(
            path=tmpdir.join("extra", "tmp", "tmpW8tdb_"),
            extras=["foo"],
            marker="python_version == '3.9'",
        ),
        vcs_req(
            vcs=VCS.Mercurial,
            project_name="AnotherProject",
            url="http://hg.example.com/MyProject@da39a3ee5e6b#subdirectory=foo/bar",
            extras=["more", "extra"],
            marker="python_version == '3.9.*'",
        ),
        vcs_req(
            vcs=VCS.Mercurial,
            project_name="AnotherProject",
            url="http://hg.example.com/MyProject@da39a3ee5e6b#subdirectory=foo/bar",
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
        url_req(
            project_name="numpy",
            url="https://a/numpy-1.9.2-cp34-none-win32.whl",
            specifier="==1.9.2",
            marker="python_version == '3.4.*' and sys_platform == 'win32'",
        ),
        url_req(
            project_name="numpy",
            url="https://a/numpy-1.9.2-cp34-none-win32.whl",
            specifier="==1.9.2",
            marker="python_version == '3.4.*' and sys_platform == 'win32'",
        ),
        vcs_req(vcs=VCS.Git, project_name="Django", url="https://github.com/django/django.git"),
        vcs_req(
            vcs=VCS.Git,
            project_name="Django",
            url="https://github.com/django/django.git@stable/2.1.x",
        ),
        vcs_req(
            vcs=VCS.Git,
            project_name="Django",
            url="https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8",
        ),
        file_req(
            project_name="django",
            url=tmpdir.join("extra", "projects", "django-2.3.zip"),
            specifier="==2.3",
            marker="python_version>='3.10'",
        ),
        file_req(
            project_name="django",
            url=tmpdir.join("extra", "projects", "django-2.3.zip"),
            specifier="==2.3",
            marker="python_version>='3.10'",
        ),
        url_req(
            project_name="torch",
            url="http://download.pytorch.org/whl/cpu/torch-1.12.1%2Bcpu-cp310-cp310-linux_x86_64.whl",
            specifier="==1.12.1+cpu",
        ),
        local_req(path=tmpdir.join("extra", "a", "local", "project"), editable=True),
        local_req(path=tmpdir.join("extra", "a", "local", "project"), editable=True),
        local_req(path=tmpdir.join("extra", "another", "local", "project"), editable=True),
        local_req(path=tmpdir.join("extra", "another", "local", "project"), editable=True),
        file_req(
            project_name="numpy",
            url=tmpdir.join("downloads", "numpy-1.9.2-cp34-none-win32.whl"),
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
