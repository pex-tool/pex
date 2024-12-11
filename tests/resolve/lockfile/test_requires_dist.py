# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.dist_metadata import Requirement
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import Artifact, LockedRequirement, LockedResolve
from pex.resolve.lockfile import requires_dist
from pex.resolve.resolved_requirement import Fingerprint, Pin
from pex.sorted_tuple import SortedTuple

req = Requirement.parse


def locked_req(
    project_name,  # type: str
    version,  # type: str
    *requirements  # type: str
):
    # type: (...) -> LockedRequirement
    return LockedRequirement.create(
        pin=Pin(project_name=ProjectName(project_name), version=Version(version)),
        artifact=Artifact.from_url(
            "https://artifact.store/{project_name}-{version}-py2.py3-none-any.whl".format(
                project_name=project_name, version=version
            ),
            fingerprint=Fingerprint(algorithm="md5", hash="abcd0123"),
        ),
        requires_dists=map(req, requirements),
    )


def locked_resolve(*locked_requirements):
    # type: (*LockedRequirement) -> LockedResolve
    return LockedResolve(locked_requirements=SortedTuple(locked_requirements))


def test_remove_unused_requires_dist_noop():
    # type: () -> None

    locked_resolve_with_no_extras = locked_resolve(
        locked_req("foo", "1.0", "bar", "baz"),
        locked_req("bar", "1.0"),
        locked_req("baz", "1.0"),
    )
    assert locked_resolve_with_no_extras == requires_dist.remove_unused_requires_dist(
        resolve_requirements=[req("foo")], locked_resolve=locked_resolve_with_no_extras
    )


def test_remove_unused_requires_dist_simple():
    # type: () -> None

    assert locked_resolve(
        locked_req("foo", "1.0", "bar", "spam"),
        locked_req("bar", "1.0"),
        locked_req("spam", "1.0"),
    ) == requires_dist.remove_unused_requires_dist(
        resolve_requirements=[req("foo")],
        locked_resolve=locked_resolve(
            locked_req("foo", "1.0", "bar", "baz; extra == 'tests'", "spam"),
            locked_req("bar", "1.0"),
            locked_req("spam", "1.0"),
        ),
    )


def test_remove_unused_requires_dist_mixed_extras():
    # type: () -> None

    assert locked_resolve(
        locked_req("foo", "1.0", "bar; extra == 'extra1'", "spam"),
        locked_req("bar", "1.0"),
        locked_req("spam", "1.0"),
    ) == requires_dist.remove_unused_requires_dist(
        resolve_requirements=[req("foo[extra1]")],
        locked_resolve=locked_resolve(
            locked_req("foo", "1.0", "bar; extra == 'extra1'", "baz; extra == 'tests'", "spam"),
            locked_req("bar", "1.0"),
            locked_req("spam", "1.0"),
        ),
    )


def test_remove_unused_requires_dist_mixed_markers():
    # type: () -> None

    assert locked_resolve(
        locked_req(
            "foo",
            "1.0",
            "bar; extra == 'extra1'",
            "baz; extra == 'tests' or python_version > '3.11'",
            "spam",
        ),
        locked_req("bar", "1.0"),
        locked_req("baz", "1.0"),
        locked_req("spam", "1.0"),
    ) == requires_dist.remove_unused_requires_dist(
        resolve_requirements=[req("foo[extra1]")],
        locked_resolve=locked_resolve(
            locked_req(
                "foo",
                "1.0",
                "bar; extra == 'extra1'",
                "baz; extra == 'tests' or python_version > '3.11'",
                "spam",
            ),
            locked_req("bar", "1.0"),
            locked_req("baz", "1.0"),
            locked_req("spam", "1.0"),
        ),
    ), (
        "The python_version marker clause might evaluate to true, which should be enough to retain "
        "the baz dep even though the 'tests' extra is never activated."
    )

    assert locked_resolve(
        locked_req(
            "foo",
            "1.0",
            "bar; extra == 'extra1'",
            "spam",
        ),
        locked_req("bar", "1.0"),
        locked_req("spam", "1.0"),
    ) == requires_dist.remove_unused_requires_dist(
        resolve_requirements=[req("foo[extra1]")],
        locked_resolve=locked_resolve(
            locked_req(
                "foo",
                "1.0",
                "bar; extra == 'extra1'",
                "baz; extra == 'tests' and python_version > '3.11'",
                "spam",
            ),
            locked_req("bar", "1.0"),
            locked_req("spam", "1.0"),
        ),
    ), "The 'tests' extra is never active; so the baz dep should never be reached."


def test_remove_unused_requires_dist_complex_markers():
    # type: () -> None

    assert locked_resolve(
        locked_req(
            "foo",
            "1.0",
            "bar; python_version < '3' and (extra == 'docs' or python_version >= '3')",
            "spam",
        ),
        locked_req("bar", "1.0"),
        locked_req("spam", "1.0"),
    ) == requires_dist.remove_unused_requires_dist(
        resolve_requirements=[req("foo")],
        locked_resolve=locked_resolve(
            locked_req(
                "foo",
                "1.0",
                "bar; python_version < '3' and (extra == 'docs' or python_version >= '3')",
                "baz; python_version == '3.11.*' and (extra == 'admin' or extra == 'docs')",
                "spam",
            ),
            locked_req("bar", "1.0"),
            locked_req("spam", "1.0"),
        ),
    )


def test_remove_unused_requires_dist_not_present_due_to_other_markers():
    # type: () -> None

    assert locked_resolve(
        locked_req("foo", "1.0", "bar", "spam"),
        locked_req("bar", "1.0"),
        locked_req("spam", "1.0"),
    ) == requires_dist.remove_unused_requires_dist(
        resolve_requirements=[req("foo")],
        locked_resolve=locked_resolve(
            locked_req(
                "foo",
                "1.0",
                "bar",
                "baz; python_version < '3'",
                "spam",
            ),
            locked_req("bar", "1.0"),
            locked_req("spam", "1.0"),
        ),
    ), (
        "Here we simulate a lock where baz is not present in the lock since the lock was for "
        "Python 3. We expect the lack of a locked baz to not trip up the elision process."
    )
