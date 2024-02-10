# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import sys
from textwrap import dedent

import pytest

from pex import requirements
from pex.compatibility import to_unicode
from pex.dist_metadata import Requirement
from pex.requirements import LocalProjectRequirement, Source
from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture
def lockfile():
    # type: () -> str
    return os.path.join(os.path.dirname(__file__), "test_export_subset.lock.json")


def test_full(
    tmpdir,  # type: Any
    lockfile,  # type: str
):
    # type: (...) -> None

    result = run_pex3("lock", "export", lockfile)
    result.assert_success()
    export = result.output

    result = run_pex3("lock", "export-subset", "--lock", lockfile)
    result.assert_success()
    export_subset = result.output

    assert (
        export == export_subset
    ), "An export-subset with no requirements should export all requirements, just like export."

    actual_requirements = []
    for parsed_requirement in requirements.parse_requirements(Source.from_text(export_subset)):
        assert not isinstance(parsed_requirement, LocalProjectRequirement)
        actual_requirements.append(parsed_requirement.requirement)

    expected_requirements = [
        Requirement.parse(to_unicode("django==1.11.29")),
        Requirement.parse(to_unicode("argon2-cffi==20.1.0")),
        Requirement.parse(to_unicode("bcrypt==3.1.7")),
        Requirement.parse(to_unicode("pytz==2023.3")),
        Requirement.parse(to_unicode("cffi==1.15.1")),
        Requirement.parse(to_unicode("six==1.16.0")),
        Requirement.parse(to_unicode("pycparser==2.21")),
    ]
    if sys.version_info[0] == 2:
        expected_requirements.append(Requirement.parse(to_unicode("enum34==1.1.10")))

    assert sorted(expected_requirements, key=str) == sorted(actual_requirements, key=str)


def test_subset(
    tmpdir,  # type: Any
    lockfile,  # type: str
):
    # type: (...) -> None

    result = run_pex3("lock", "export-subset", "django", "--lock", lockfile)
    result.assert_success()

    assert (
        dedent(
            """\
            django==1.11.29 \\
              --hash=sha256:014e3392058d94f40569206a24523ce254d55ad2f9f46c6550b0fe2e4f94cf3f \\
              --hash=sha256:4200aefb6678019a0acf0005cd14cfce3a5e6b9b90d06145fcdd2e474ad4329c
            pytz==2023.3 \\
              --hash=sha256:a151b3abb88eda1d4e34a9814df37de2a80e301e68ba0fd856fb9b46bfbbbffb \\
              --hash=sha256:1d8ce29db189191fb55338ee6d0387d82ab59f3d00eac103412d64e0ebd0c588
            """
        )
        == result.output
    ), (
        "Django without extras only depends on pytz and both are available in the lock in sdist "
        "and universal wheel formats"
    )
