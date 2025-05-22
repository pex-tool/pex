# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import os.path
import re
from collections import defaultdict
from textwrap import dedent

import pytest

from pex.artifact_url import VCS, ArtifactURL, Fingerprint
from pex.common import safe_mkdtemp, safe_open
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import (
    FileArtifact,
    UnFingerprintedLocalProjectArtifact,
    UnFingerprintedVCSArtifact,
)
from pex.resolve.lockfile.pep_751 import Pylock, _calculate_marker, _elide_extras
from pex.result import ResultError, try_
from pex.third_party.packaging.markers import Marker
from pex.typing import TYPE_CHECKING
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import DefaultDict, Mapping, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def assert_markers_equal(
    expected,  # type: Marker
    actual,  # type: Optional[Marker]
):
    # type: (...) -> None

    assert actual is not None

    # N.B.: The string conversion is needed to cover Python 2.7, 3.5 and 3.6 which use vendored
    # packaging 20.9 and 21.3. In those versions of packaging, `__eq__` is not defined for
    # `Marker`. In later versions it is (and is based off of `str`).
    assert str(expected) == str(actual)


def test_elide_extras():
    assert _elide_extras(Marker("extra == 'bob'")) is None
    assert _elide_extras(Marker("extra == 'bob' or extra == 'bill'")) is None

    def assert_elide_extras(
        expected,  # type: str
        original,  # type: str
    ):
        # type: (...) -> None

        assert_markers_equal(Marker(expected), _elide_extras(Marker(original)))

    assert_elide_extras(
        "python_version == '3.14.*'",
        "(extra == 'bob' or extra == 'bill') and python_version == '3.14.*'",
    )
    assert_elide_extras(
        "python_version == '3.14.*'",
        "python_version == '3.14.*' and (extra == 'bob' or extra == 'bill')",
    )
    assert_elide_extras(
        "python_version == '3.14.*'",
        "(extra == 'bob' and python_version == '3.14.*') or extra == 'bill'",
    )
    assert_elide_extras(
        (
            "("
            "   python_version == '3.14.*' and sys_platform == 'win32'"
            ") or python_version == '3.11.*'"
        ),
        (
            "("
            "   python_version == '3.14.*' and sys_platform == 'win32' and ("
            "       extra == 'bob' or extra == 'bill'"
            "   )"
            ") or python_version == '3.11.*'"
        ),
    )


@attr.s(frozen=True)
class Dependency(object):
    project = attr.ib()  # type: ProjectName
    dependency = attr.ib()  # type: ProjectName
    marker = attr.ib(default=None)  # type: Optional[Marker]


@attr.s(frozen=True)
class Project(object):
    name = attr.ib()  # type: ProjectName

    def depends_on(
        self,
        project,  # type: str
        marker=None,  # type: Optional[str]
    ):
        # type: (...) -> Dependency

        return Dependency(
            project=self.name,
            dependency=ProjectName(project),
            marker=Marker(marker) if marker else None,
        )


def project(name):
    # type: (str) -> Project
    return Project(ProjectName(name))


def create_dependants_mapping(*dependencies):
    # type: (*Dependency) -> Mapping[ProjectName, OrderedSet[Tuple[ProjectName, Optional[Marker]]]]

    dependants_by_project_name = defaultdict(
        OrderedSet
    )  # type: DefaultDict[ProjectName, OrderedSet[Tuple[ProjectName, Optional[Marker]]]]
    for dependency in dependencies:
        dependants_by_project_name[dependency.dependency].add(
            (dependency.project, dependency.marker)
        )
    return dependants_by_project_name


def test_calculate_marker_none():
    # type: () -> None

    dependants_mapping = create_dependants_mapping(
        project("A").depends_on("B"),
        project("A").depends_on("C"),
        project("C").depends_on("B"),
    )

    assert _calculate_marker(ProjectName("A"), dependants_mapping) is None
    assert _calculate_marker(ProjectName("B"), dependants_mapping) is None
    assert _calculate_marker(ProjectName("C"), dependants_mapping) is None


def test_calculate_marker_multipath_none():
    # type: () -> None

    # Here B is depended on via two paths:
    # 1. A -> B (with marker)
    # 2. A -> C -> B
    # The second path is always reachable without regard to markers; so B should always be
    # installed.

    dependants_mapping = create_dependants_mapping(
        project("A").depends_on("B", marker="python_version == '3.9.*'"),
        project("A").depends_on("C"),
        project("C").depends_on("B"),
    )

    assert _calculate_marker(ProjectName("A"), dependants_mapping) is None
    assert _calculate_marker(ProjectName("B"), dependants_mapping) is None
    assert _calculate_marker(ProjectName("C"), dependants_mapping) is None


def test_calculate_marker_multipath_or():
    # type: () -> None

    dependants_mapping = create_dependants_mapping(
        project("A").depends_on("B", marker="python_version == '3.9.*'"),
        project("A").depends_on("C"),
        project("C").depends_on("B", marker="sys_platform == 'win32'"),
    )

    assert _calculate_marker(ProjectName("A"), dependants_mapping) is None
    assert_markers_equal(
        Marker("python_version == '3.9.*' or sys_platform == 'win32'"),
        _calculate_marker(ProjectName("B"), dependants_mapping),
    )
    assert _calculate_marker(ProjectName("C"), dependants_mapping) is None


def test_calculate_marker_multipath_indirect_or():
    # type: () -> None

    dependants_mapping = create_dependants_mapping(
        project("A").depends_on("B", marker="python_version == '3.9.*'"),
        project("A").depends_on("C", marker="sys_platform == 'win32'"),
        project("C").depends_on("B"),
    )

    assert _calculate_marker(ProjectName("A"), dependants_mapping) is None
    assert_markers_equal(
        Marker("python_version == '3.9.*' or sys_platform == 'win32'"),
        _calculate_marker(ProjectName("B"), dependants_mapping),
    )
    assert_markers_equal(
        Marker("sys_platform == 'win32'"), _calculate_marker(ProjectName("C"), dependants_mapping)
    )


def test_calculate_marker_multipath_and_or():
    # type: () -> None

    dependants_mapping = create_dependants_mapping(
        project("A").depends_on("B", marker="python_version == '3.9.*'"),
        project("A").depends_on("C", marker="sys_platform == 'win32'"),
        project("C").depends_on("B", marker="python_version >= '3.9'"),
    )

    assert _calculate_marker(ProjectName("A"), dependants_mapping) is None
    assert_markers_equal(
        Marker(
            "python_version == '3.9.*' or (python_version >= '3.9' and sys_platform == 'win32')"
        ),
        _calculate_marker(ProjectName("B"), dependants_mapping),
    )
    assert_markers_equal(
        Marker("sys_platform == 'win32'"), _calculate_marker(ProjectName("C"), dependants_mapping)
    )


def test_calculate_marker_indirect_and():
    # type: () -> None

    dependants_mapping = create_dependants_mapping(
        project("A").depends_on("B", marker="python_version == '3.9.*'"),
        project("B").depends_on("C"),
        project("C").depends_on("D", marker="sys_platform == 'win32'"),
    )

    assert _calculate_marker(ProjectName("A"), dependants_mapping) is None
    assert_markers_equal(
        Marker("python_version == '3.9.*'"),
        _calculate_marker(ProjectName("B"), dependants_mapping),
    )
    assert_markers_equal(
        Marker("python_version == '3.9.*'"),
        _calculate_marker(ProjectName("C"), dependants_mapping),
    )
    assert_markers_equal(
        Marker("sys_platform == 'win32' and python_version == '3.9.*'"),
        _calculate_marker(ProjectName("D"), dependants_mapping),
    )


def parse_lock(
    content,  # type: str
    expected_package_count=1,  # type: int
    path=None,  # type: Optional[str]
):
    # type: (...) -> Pylock

    lock_path = path or os.path.join(safe_mkdtemp(), "pylock.toml")
    with safe_open(lock_path, mode="w") as fp:
        fp.write(
            dedent(
                """\
                lock-version = "1.0"
                created-by = "test"
                
                {content}
                """
            ).format(content=content)
        )
    pylock = try_(Pylock.parse(lock_path))
    assert Version("1.0") == pylock.lock_version
    assert "test" == pylock.created_by
    assert len(pylock.packages) == expected_package_count
    return pylock


def test_pylock_parse_toplevel_items():
    pylock = parse_lock(
        dedent(
            """\
            environments = [
                "platform_system == \\"Darwin\\" and python_version >=\\"3.12\\"",
                "platform_system == \\"Linux\\""
            ]
            requires-python = ">=3.9"
            extras = ["admin"]
            dependency-groups = ["dev", "debug"]
            default-groups = ["dev"]
            """
        ),
        expected_package_count=0,
    )

    assert (
        'platform_system == "Darwin" and python_version >= "3.12"',
        'platform_system == "Linux"',
    ) == tuple(map(str, pylock.environments))
    assert ">=3.9" == str(pylock.requires_python)
    assert frozenset(["admin"]) == pylock.extras
    assert frozenset(["dev", "debug"]) == pylock.dependency_groups
    assert frozenset(["dev"]) == pylock.default_groups


def test_pylock_parse_sdist_url():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            version = "1.2.3"
            [packages.sdist]
            name = "foo-1.2.3.tar.gz"
            url = "https://example.org/Foo-1.2.3.tar.gz"
            hashes = {md5 = "4321dcba", sha256 = "abcd1234"}
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert Version("1.2.3") == package.version
    assert isinstance(package.artifact, FileArtifact)
    assert not package.artifact.verified
    assert package.artifact.is_source
    assert "Foo-1.2.3.tar.gz" == package.artifact.filename
    assert ArtifactURL.parse("https://example.org/Foo-1.2.3.tar.gz") == package.artifact.url
    assert (
        Fingerprint(algorithm="sha256", hash="abcd1234") == package.artifact.fingerprint
    ), "Expected the strongest hash to be selected."
    assert len(package.additional_wheels) == 0


def test_pylock_parse_sdist_relative_path():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            version = "1.2.3"
            [packages.sdist]
            name = "foo-1.2.3.tar.gz"
            path = "dists/foo-1.2.3.tar.gz"
            hashes = {md5 = "4321dcba"}
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert Version("1.2.3") == package.version
    assert isinstance(package.artifact, FileArtifact)
    assert not package.artifact.verified
    assert package.artifact.is_source
    assert "foo-1.2.3.tar.gz" == package.artifact.filename
    assert (
        ArtifactURL.parse(
            "file://{lock_path}/dists/foo-1.2.3.tar.gz".format(
                lock_path=os.path.dirname(pylock.source)
            )
        )
        == package.artifact.url
    )
    assert Fingerprint(algorithm="md5", hash="4321dcba")
    assert len(package.additional_wheels) == 0


def test_pylock_parse_sdist_absolute_path():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            version = "1.2.3"
            [packages.sdist]
            name = "foo-1.2.3.tar.gz"
            path = "/mnt/nfs/dists/foo-1.2.3.tar.gz"
            hashes = {md5 = "4321dcba"}
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert Version("1.2.3") == package.version
    assert isinstance(package.artifact, FileArtifact)
    assert not package.artifact.verified
    assert package.artifact.is_source
    assert "foo-1.2.3.tar.gz" == package.artifact.filename
    assert ArtifactURL.parse("file:///mnt/nfs/dists/foo-1.2.3.tar.gz") == package.artifact.url
    assert Fingerprint(algorithm="md5", hash="4321dcba")
    assert len(package.additional_wheels) == 0


def test_pylock_parse_wheel():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            version = "1.2.3"
            [[packages.wheels]]
            name = "foo-1.2.3-py3-none-any.whl"
            url = "file:///mnt/nfs/dists/foo-1.2.3-py3-none-any.whl"
            hashes = {md5 = "4321dcba", sha1 = "abcd1234"}
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert Version("1.2.3") == package.version
    assert isinstance(package.artifact, FileArtifact)
    assert not package.artifact.verified
    assert package.artifact.is_wheel
    assert "foo-1.2.3-py3-none-any.whl" == package.artifact.filename
    assert (
        ArtifactURL.parse("file:///mnt/nfs/dists/foo-1.2.3-py3-none-any.whl")
        == package.artifact.url
    )
    assert (
        Fingerprint(algorithm="sha1", hash="abcd1234") == package.artifact.fingerprint
    ), "Expected the strongest hash to be selected."
    assert len(package.additional_wheels) == 0


def test_pylock_parse_wheels():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            version = "1.2.3"
            [[packages.wheels]]
            name = "foo-1.2.3-py3-none-any.whl"
            url = "file:///mnt/nfs/dists/foo-1.2.3-py3-none-any.whl"
            hashes = {md5 = "4321dcba", sha1 = "abcd1234"}
            [[packages.wheels]]
            name = "foo-1.2.3-py2-none-any.whl"
            url = "https://example.org/Foo-1.2.3-py2-none-any.whl"
            hashes = {sha256 = "4321dcba"}
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert Version("1.2.3") == package.version

    assert isinstance(package.artifact, FileArtifact)
    assert not package.artifact.verified
    assert package.artifact.is_wheel
    assert "foo-1.2.3-py3-none-any.whl" == package.artifact.filename
    assert (
        ArtifactURL.parse("file:///mnt/nfs/dists/foo-1.2.3-py3-none-any.whl")
        == package.artifact.url
    )
    assert (
        Fingerprint(algorithm="sha1", hash="abcd1234") == package.artifact.fingerprint
    ), "Expected the strongest hash to be selected."
    assert len(package.additional_wheels) == 1

    additional_wheel = package.additional_wheels[0]
    assert isinstance(additional_wheel, FileArtifact)
    assert not additional_wheel.verified
    assert additional_wheel.is_wheel
    assert "Foo-1.2.3-py2-none-any.whl" == additional_wheel.filename
    assert (
        ArtifactURL.parse("https://example.org/Foo-1.2.3-py2-none-any.whl") == additional_wheel.url
    )
    assert Fingerprint(algorithm="sha256", hash="4321dcba") == additional_wheel.fingerprint


def test_pylock_parse_sdist_and_wheels():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            version = "1.2.3"
            [packages.sdist]
            name = "foo-1.2.3.tar.gz"
            url = "https://example.org/foo-1.2.3.tar.gz"
            hashes = {md5 = "4321dcba", sha256 = "abcd1234"}
            [[packages.wheels]]
            name = "foo-1.2.3-py3-none-any.whl"
            url = "file:///mnt/nfs/dists/foo-1.2.3-py3-none-any.whl"
            hashes = {md5 = "4321dcba", sha1 = "abcd1234"}
            [[packages.wheels]]
            url = "https://example.org/foo-1.2.3-py2-none-any.whl"
            hashes = {sha256 = "4321dcba"}
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert Version("1.2.3") == package.version

    assert isinstance(package.artifact, FileArtifact)
    assert not package.artifact.verified
    assert package.artifact.is_source
    assert "foo-1.2.3.tar.gz" == package.artifact.filename
    assert ArtifactURL.parse("https://example.org/foo-1.2.3.tar.gz") == package.artifact.url
    assert (
        Fingerprint(algorithm="sha256", hash="abcd1234") == package.artifact.fingerprint
    ), "Expected the strongest hash to be selected."
    assert len(package.additional_wheels) == 2

    wheel1 = package.additional_wheels[0]
    assert isinstance(wheel1, FileArtifact)
    assert not wheel1.verified
    assert wheel1.is_wheel
    assert "foo-1.2.3-py3-none-any.whl" == wheel1.filename
    assert ArtifactURL.parse("file:///mnt/nfs/dists/foo-1.2.3-py3-none-any.whl") == wheel1.url
    assert (
        Fingerprint(algorithm="sha1", hash="abcd1234") == wheel1.fingerprint
    ), "Expected the strongest hash to be selected."

    wheel2 = package.additional_wheels[1]
    assert isinstance(wheel2, FileArtifact)
    assert not wheel2.verified
    assert wheel2.is_wheel
    assert "foo-1.2.3-py2-none-any.whl" == wheel2.filename
    assert ArtifactURL.parse("https://example.org/foo-1.2.3-py2-none-any.whl") == wheel2.url
    assert Fingerprint(algorithm="sha256", hash="4321dcba") == wheel2.fingerprint


def test_pylock_parse_archive():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            version = "1.2.3"
            marker = "python_version >= \\"3.9\\""
            [packages.archive]
            name = "foo-1.2.3.tar.gz"
            url = "https://example.org/foo-1.2.3.tar.gz"
            hashes = {sha256 = "abcd1234"}
            subdirectory = "bar"
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert Version("1.2.3") == package.version
    assert 'python_version >= "3.9"' == str(package.marker)
    assert isinstance(package.artifact, FileArtifact)
    assert not package.artifact.verified
    assert package.artifact.is_source
    assert "foo-1.2.3.tar.gz" == package.artifact.filename
    assert ArtifactURL.parse("https://example.org/foo-1.2.3.tar.gz") == package.artifact.url
    assert Fingerprint(algorithm="sha256", hash="abcd1234") == package.artifact.fingerprint
    assert "bar" == package.artifact.subdirectory
    assert len(package.additional_wheels) == 0


def test_pylock_parse_directory():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            [packages.directory]
            path = "."
            editable = true
            subdirectory = "foo"
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert package.version is None
    assert isinstance(package.artifact, UnFingerprintedLocalProjectArtifact)
    assert package.artifact.verified
    assert os.path.join(os.path.dirname(pylock.source), "foo") == package.artifact.directory
    assert package.artifact.editable
    assert package.artifact.subdirectory is None
    assert len(package.additional_wheels) == 0


def test_pylock_parse_vcs():
    # type: () -> None

    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "foo"
            [packages.vcs]
            type = "git"
            requested-revision = "main"
            commit-id = "abcd1234"
            url = "https://github.com/foo/foo"
            subdirectory = "bar"
            """
        )
    )
    package = pylock.packages[0]

    assert ProjectName("foo") == package.project_name
    assert isinstance(package.artifact, UnFingerprintedVCSArtifact)
    assert package.artifact.verified
    assert package.artifact.vcs is VCS.Git
    assert "main" == package.artifact.requested_revision
    assert "abcd1234" == package.artifact.commit_id
    assert ArtifactURL.parse("https://github.com/foo/foo") == package.artifact.url
    assert "bar" == package.artifact.subdirectory
    assert len(package.additional_wheels) == 0


def test_pylock_parse_dependencies():
    pylock = parse_lock(
        dedent(
            """\
            [[packages]]
            name = "A"
            version = "1"
            dependencies = [
                {name = "B", wheels = [{hashes = {sha1 = "123"}}]},
                {name = "E", wheels = [{"url" = "https://example.org/e-5-py3-none-any.whl"}]}
            ]
            wheels = [{"url" = "https://example.org/a-1-py3-none-any.whl", hashes = {md5 = "abc"}}]
            
            [[packages]]
            name = "B"
            version = "2"
            dependencies = [{name = "C"}]
            [[packages.wheels]]
            url = "https://example.org/b-2-py3-none-any.whl"
            hashes = {md5 = "def", "sha1" = "123"}
            
            [[packages]]
            name = "C"
            version = "3"
            wheels = [{"url" = "https://example.org/c-3-py3-none-any.whl", hashes = {md5 = "ghi"}}]
            
            [[packages]]
            name = "D"
            version = "4"
            dependencies = [{name = "E"}]
            wheels = [{"url" = "https://example.org/d-4-py3-none-any.whl", hashes = {md5 = "jkl"}}]
            
            [[packages]]
            name = "E"
            version = "5"
            wheels = [{"url" = "https://example.org/e-5-py3-none-any.whl", hashes = {md5 = "mno"}}]
            """
        ),
        expected_package_count=5,
    )

    packages_by_project_name = {package.project_name: package for package in pylock.packages}
    package_A = packages_by_project_name.pop(ProjectName("A"))
    package_B = packages_by_project_name.pop(ProjectName("B"))
    package_C = packages_by_project_name.pop(ProjectName("C"))
    package_D = packages_by_project_name.pop(ProjectName("D"))
    package_E = packages_by_project_name.pop(ProjectName("E"))
    assert not packages_by_project_name
    assert (package_B, package_E) == package_A.dependencies
    assert tuple([package_C]) == package_B.dependencies
    assert not package_C.dependencies
    assert tuple([package_E]) == package_D.dependencies
    assert not package_E.dependencies


def assert_lock_error(
    lock_path,  # type: str
    match,  # type: str
    content,  # type: str
):
    # type: (...) -> None
    with pytest.raises(ResultError, match=r"^{match}$".format(match=re.escape(match))):
        parse_lock(content, path=lock_path)


def test_pylock_parse_errors(tmpdir):
    # type: (Tempdir) -> None

    lock_path = tmpdir.join("pylock.toml")
    assert_pylock_error = functools.partial(assert_lock_error, lock_path)

    assert_pylock_error(
        "Failed to parse the PEP-751 lock at {lock_path}. "
        "Error parsing content at packages[0].\n"
        "A value for packages[0].name is required.".format(lock_path=lock_path),
        dedent(
            """\
            [[packages]]
            """
        ),
    )

    assert_pylock_error(
        "Failed to parse the PEP-751 lock at {lock_path}. "
        'Error parsing content at packages[0]{{name = "foo"}}.\n'
        "Package must define an artifact.".format(lock_path=lock_path),
        dedent(
            """\
            [[packages]]
            name = "foo"
            """
        ),
    )

    assert_pylock_error(
        "Failed to parse the PEP-751 lock at {lock_path}. "
        'Error parsing content at packages[0]{{name = "foo"}}.\n'
        'These artifacts are mutually exclusive with packages[0]{{name = "foo"}}.vcs:\n'
        '+ packages[0]{{name = "foo"}}.sdist\n'
        '+ packages[0]{{name = "foo"}}.wheels'.format(lock_path=lock_path),
        dedent(
            """\
            [[packages]]
            name = "foo"
            vcs = {type = "git"}
            sdist = {name = "foo-1.0.tar.gz"}
            wheels = [{name = "foo-1.0-py2.py3-none-any.whl"}]
            """
        ),
    )

    assert_pylock_error(
        "Failed to parse the PEP-751 lock at {lock_path}. "
        'Error parsing content at packages[0]{{name = "A"}}.dependencies[0]{{name = "C"}}.\n'
        "The A package depends on C, but there is no C package in the packages array.".format(
            lock_path=lock_path
        ),
        dedent(
            """\
            [[packages]]
            name = "A"
            version = "1"
            dependencies = [{name = "C"}]
            directory = {path = "A"}
            
            [[packages]]
            name = "B"
            version = "2"
            directory = {path = "B"}
            """
        ),
    )

    assert_pylock_error(
        "Failed to parse the PEP-751 lock at {lock_path}. "
        'Error parsing content at packages[0]{{name = "A"}}.dependencies[0]{{name = "B"}}.\n'
        "No matching B package could be found for A dependencies[0].".format(lock_path=lock_path),
        dedent(
            """\
            [[packages]]
            name = "A"
            version = "1"
            dependencies = [{name = "B", version = "1"}]
            directory = {path = "A"}
            
            [[packages]]
            name = "B"
            version = "2"
            directory = {path = "B"}
            """
        ),
    )

    assert_pylock_error(
        "Failed to parse the PEP-751 lock at {lock_path}. "
        'Error parsing content at packages[0]{{name = "A"}}.dependencies[0]{{name = "B"}}.\n'
        "More than one package matches A dependencies[0]:\n"
        "+ packages[1]\n"
        "+ packages[2]".format(lock_path=lock_path),
        dedent(
            """\
            [[packages]]
            name = "A"
            version = "1"
            dependencies = [{name = "B", version = "1"}]
            directory = {path = "A"}
            
            [[packages]]
            name = "B"
            version = "1"
            directory = {path = "B", subdirectory = "standard-b"}
            
            [[packages]]
            name = "B"
            version = "1"
            directory = {path = "B", subdirectory = "special-b"}
            """
        ),
    )
