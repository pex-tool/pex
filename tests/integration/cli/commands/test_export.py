# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os.path
import sys
from textwrap import dedent

from pex.dist_metadata import Requirement
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion
from pex.resolve.locked_resolve import Artifact, LockedRequirement, LockedResolve, LockStyle
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.resolved_requirement import Fingerprint, Pin
from pex.resolve.resolver_configuration import ResolverVersion
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Text

    import attr  # vendor:skip
else:
    from pex.third_party import attr


UNIVERSAL_ANSICOLORS = Lockfile(
    pex_version="42",
    style=LockStyle.UNIVERSAL,
    requires_python=SortedTuple(),
    target_systems=SortedTuple(),
    pip_version=PipVersion.DEFAULT,
    resolver_version=ResolverVersion.PIP_2020,
    requirements=SortedTuple([Requirement.parse("ansicolors")]),
    constraints=SortedTuple(),
    allow_prereleases=False,
    allow_wheels=True,
    only_wheels=SortedTuple(),
    allow_builds=True,
    only_builds=SortedTuple(),
    prefer_older_binary=False,
    use_pep517=None,
    build_isolation=True,
    transitive=True,
    locked_resolves=SortedTuple(
        [
            LockedResolve(
                locked_requirements=SortedTuple(
                    [
                        LockedRequirement(
                            pin=Pin(ProjectName("ansicolors"), Version("1.1.8")),
                            artifact=Artifact.from_url(
                                url="http://localhost:9999/ansicolors-1.1.8-py2.py3-none-any.whl",
                                fingerprint=Fingerprint(algorithm="md5", hash="abcd1234"),
                            ),
                            additional_artifacts=SortedTuple(
                                [
                                    Artifact.from_url(
                                        url="http://localhost:9999/ansicolors-1.1.8.tar.gz",
                                        fingerprint=Fingerprint(algorithm="sha1", hash="ef567890"),
                                    )
                                ]
                            ),
                        )
                    ]
                )
            )
        ]
    ),
    local_project_requirement_mapping={},
)


def export(
    tmpdir,  # type: Any
    lockfile,  # type: Lockfile
    *export_args  # type: str
):
    # type: (...) -> Text
    lock = os.path.join(str(tmpdir), "lock.json")
    with open(lock, "w") as fp:
        json.dump(json_codec.as_json_data(lockfile), fp, sort_keys=True, indent=2)

    result = run_pex3("lock", "export", lock, *export_args)
    result.assert_success()
    return result.output


def test_export_multiple_artifacts(tmpdir):
    # type: (Any) -> None

    assert (
        dedent(
            """\
            ansicolors==1.1.8 \\
              --hash=md5:abcd1234 \\
              --hash=sha1:ef567890
            """
        )
        == export(tmpdir, UNIVERSAL_ANSICOLORS)
    )


def test_export_single_artifact(tmpdir):
    # type: (Any) -> None

    assert (
        dedent(
            """\
            ansicolors==1.1.8 \\
              --hash=sha1:ef567890
            """
        )
        == export(tmpdir, attr.evolve(UNIVERSAL_ANSICOLORS, allow_wheels=False))
    )


def test_export_normalizes_name_but_not_version(tmpdir):
    # type: (Any) -> None

    assert dedent(
        """\
             twitter-common-decorators==1.3.0 \\
               --hash=md5:abcd1234 \\
               --hash=sha1:ef567890
            """
    ) == export(
        tmpdir,
        attr.evolve(
            UNIVERSAL_ANSICOLORS,
            requirements=SortedTuple([Requirement.parse("twitter.common.decorators")]),
            locked_resolves=SortedTuple(
                [
                    LockedResolve(
                        locked_requirements=SortedTuple(
                            [
                                LockedRequirement(
                                    pin=Pin(
                                        ProjectName("twitter.common.decorators"),
                                        Version("1.3.0"),
                                    ),
                                    artifact=Artifact.from_url(
                                        url="http://localhost:9999/twitter.common.decorators-1.3.0-py2.py3-none-any.whl",
                                        fingerprint=Fingerprint(algorithm="md5", hash="abcd1234"),
                                    ),
                                    additional_artifacts=SortedTuple(
                                        [
                                            Artifact.from_url(
                                                url="http://localhost:9999/twitter.common.decorators-1.3.0.tar.gz",
                                                fingerprint=Fingerprint(
                                                    algorithm="sha1", hash="ef567890"
                                                ),
                                            )
                                        ]
                                    ),
                                )
                            ],
                        ),
                    )
                ]
            ),
        ),
    )


def test_export_sort_by(tmpdir):
    # type: (Any) -> None
    ansicolors_plus_attrs = attr.evolve(
        UNIVERSAL_ANSICOLORS,
        requirements=[
            Requirement.parse("a-package"),
            Requirement.parse("z-package"),
        ],
        locked_resolves=[
            attr.evolve(
                UNIVERSAL_ANSICOLORS.locked_resolves[0],
                locked_requirements=(
                    [
                        LockedRequirement(
                            pin=Pin(ProjectName("a-package"), Version("1.1.8")),
                            artifact=Artifact.from_url(
                                url="http://localhost:9999/a-package-1.1.8-py2.py3-none-any.whl",
                                fingerprint=Fingerprint(algorithm="md5", hash="abcd1234"),
                            ),
                        ),
                        LockedRequirement(
                            pin=Pin(ProjectName("other-package"), Version("0.1.3")),
                            artifact=Artifact.from_url(
                                url="http://localhost:9999/other-package-0.1.3-py2.py3-none-any.whl",
                                fingerprint=Fingerprint(algorithm="sha256", hash="spamspam"),
                            ),
                        ),
                        LockedRequirement(
                            pin=Pin(ProjectName("z-package"), Version("22.1.0")),
                            requires_dists=SortedTuple([Requirement("other-package")]),
                            artifact=Artifact.from_url(
                                url="http://localhost:9999/z-package-22.1.0-py2.py3-none-any.whl",
                                fingerprint=Fingerprint(algorithm="sha256", hash="spameggs"),
                            ),
                        ),
                    ]
                ),
            )
        ],
    )
    assert (
        dedent(
            """\
            a-package==1.1.8 \\
              --hash=md5:abcd1234
            z-package==22.1.0 \\
              --hash=sha256:spameggs
            other-package==0.1.3 \\
              --hash=sha256:spamspam
            """
        )
        == export(tmpdir, ansicolors_plus_attrs, "--sort-by=specificity")
    )

    assert (
        dedent(
            """\
            a-package==1.1.8 \\
              --hash=md5:abcd1234
            other-package==0.1.3 \\
              --hash=sha256:spamspam
            z-package==22.1.0 \\
              --hash=sha256:spameggs
            """
        )
        == export(tmpdir, ansicolors_plus_attrs, "--sort-by=project-name")
    )


def test_export_respects_target(tmpdir):
    # type: (Any) -> None

    ansicolors_plus_pywin32 = attr.evolve(
        UNIVERSAL_ANSICOLORS,
        requirements=SortedTuple(
            [
                Requirement.parse("ansicolors"),
                Requirement.parse('pywin32; sys_platform == "win32"'),
            ]
        ),
        locked_resolves=SortedTuple(
            [
                attr.evolve(
                    UNIVERSAL_ANSICOLORS.locked_resolves[0],
                    locked_requirements=SortedTuple(
                        list(UNIVERSAL_ANSICOLORS.locked_resolves[0].locked_requirements)
                        + [
                            LockedRequirement(
                                pin=Pin(ProjectName("pywin32"), Version("227")),
                                artifact=Artifact.from_url(
                                    url="http://localhost:9999/pywin32-227-cp39-cp39-win32.whl",
                                    fingerprint=Fingerprint(algorithm="sha256", hash="spameggs"),
                                ),
                            )
                        ]
                    ),
                )
            ]
        ),
    )
    assert dedent(
        """\
            ansicolors==1.1.8 \\
              --hash=md5:abcd1234 \\
              --hash=sha1:ef567890
            pywin32==227 \\
              --hash=sha256:spameggs
            """
    ) == export(
        tmpdir,
        ansicolors_plus_pywin32,
        "--complete-platform",
        json.dumps(
            {
                "marker_environment": {"sys_platform": "win32"},
                "compatible_tags": ["cp39-cp39-win32", "py3-none-any"],
            }
        ),
    ), (
        "A win32 foreign target should get both ansicolors cross-platform artifacts as well as "
        "the platform-specific pywin32 wheel."
    )

    assert (
        dedent(
            """\
        ansicolors==1.1.8 \\
          --hash=md5:abcd1234 \\
          --hash=sha1:ef567890
        """
        )
        == export(tmpdir, ansicolors_plus_pywin32, "--python", sys.executable)
    ), "The local interpreter doesn't support Windows; so we should just get ansicolors artifacts."
