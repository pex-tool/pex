# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from collections import defaultdict

from pex.orderedset import OrderedSet
from pex.pep_503 import ProjectName
from pex.resolve.lockfile.pep_751 import _calculate_marker, _elide_extras
from pex.third_party.packaging.markers import Marker
from pex.typing import TYPE_CHECKING

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
