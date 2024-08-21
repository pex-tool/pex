# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re

import pytest

from pex.atomic_directory import atomic_directory
from pex.pep_427 import InstallableType
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersion
from pex.resolve.locked_resolve import FileArtifact
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.resolved_requirement import Pin
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.cli import run_pex3
from testing.find_links import FindLinksRepo

if TYPE_CHECKING:
    from typing import Any, List


@pytest.fixture(scope="session")
def find_links(shared_integration_test_tmpdir):
    # type: (str) -> str

    test_issue_2343_chroot = os.path.join(shared_integration_test_tmpdir, "test_issue_2343_chroot")
    with atomic_directory(test_issue_2343_chroot) as chroot:
        if not chroot.is_finalized():
            pip_version = PipVersion.DEFAULT
            find_links = os.path.join(chroot.work_dir, "find_links")
            find_links_repo = FindLinksRepo.create(find_links, pip_version)

            # N.B.: Since we are setting up a find links repo for offline lock resolves, we grab one
            # distribution online to allow the current Pip version to bootstrap itself if needed.
            result = find_links_repo.resolver.resolve_requirements(
                [
                    "ansicolors==1.1.8",
                    str(pip_version.setuptools_requirement),
                    str(pip_version.wheel_requirement),
                ],
                result_type=InstallableType.WHEEL_FILE,
            )
            for resolved_distribution in result.distributions:
                find_links_repo.host(resolved_distribution.distribution.location)

            for version in "1", "2":
                find_links_repo.make_sdist("only_sdist", version=version)
                find_links_repo.make_wheel("both", version=version)
                find_links_repo.make_sdist("both", version=version)

    return os.path.join(test_issue_2343_chroot, "find_links")


@pytest.fixture
def repo_args(find_links):
    # type: (str) -> List[str]
    return [
        "--no-pypi",
        "-f",
        find_links,
    ]


def test_no_build_no_wheel_honored_pex(repo_args):
    # type: (List[str]) -> None

    run_pex_command(
        args=repo_args
        + [
            "--no-build",
            "ansicolors",
            "both",
            "--",
            "-c",
            "import both, colors",
        ]
    ).assert_success()
    run_pex_command(args=repo_args + ["--no-wheel", "ansicolors", "both"]).assert_failure(
        expected_error_re=r".*\bERROR: No matching distribution found for ansicolors\b.*",
        re_flags=re.DOTALL,
    )

    run_pex_command(
        args=repo_args
        + [
            "--no-wheel",
            "only_sdist",
            "both",
            "--",
            "-c",
            "import both, only_sdist",
        ]
    ).assert_success()
    run_pex_command(args=repo_args + ["--no-build", "only_sdist", "both"]).assert_failure(
        expected_error_re=r".*\bERROR: No matching distribution found for only_sdist\b.*",
        re_flags=re.DOTALL,
    )


def test_only_build_honored_pex(repo_args):
    # type: (List[str]) -> None

    run_pex_command(
        args=repo_args
        + [
            "--only-build",
            "sdist_only",
            "--only-build",
            "both",
            "ansicolors",
            "both",
            "only_sdist",
            "--",
            "-c",
            "import both, colors, only_sdist",
        ]
    ).assert_success()
    run_pex_command(args=repo_args + ["--only-build", "ansicolors", "ansicolors"]).assert_failure(
        expected_error_re=r".*\bERROR: No matching distribution found for ansicolors\b.*",
        re_flags=re.DOTALL,
    )


def test_only_wheel_honored_pex(repo_args):
    # type: (List[str]) -> None

    run_pex_command(
        args=repo_args
        + [
            "--only-wheel",
            "ansicolors",
            "--only-wheel",
            "both",
            "ansicolors",
            "both",
            "only_sdist",
            "--",
            "-c",
            "import both, colors, only_sdist",
        ]
    ).assert_success()
    run_pex_command(args=repo_args + ["--only-wheel", "only_sdist", "only_sdist"]).assert_failure(
        expected_error_re=r".*\bERROR: No matching distribution found for only_sdist\b.*",
        re_flags=re.DOTALL,
    )


def assert_lock_single(
    lock,  # type: str
    expected_project_name,  # type: str
    expected_version,  # type: str
    is_source,  # type: bool
):
    # type: (...) -> Lockfile
    lock_file = json_codec.load(lock)
    locked_requirements = [
        locked_requirement
        for locked_resolve in lock_file.locked_resolves
        for locked_requirement in locked_resolve.locked_requirements
    ]

    assert 1 == len(locked_requirements)
    locked_requirement = locked_requirements[0]
    assert (
        Pin(ProjectName(expected_project_name), Version(expected_version)) == locked_requirement.pin
    )

    artifacts = list(locked_requirement.iter_artifacts())
    assert 1 == len(artifacts)
    assert isinstance(artifacts[0], FileArtifact)
    assert is_source == artifacts[0].is_source
    return lock_file


def test_only_build_honored_lock(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        *(
            [
                "lock",
                "create",
            ]
            + repo_args
            + [
                "--style",
                "universal",
                "--only-build",
                "both",
                "both<2",
                "--indent",
                "2",
                "-o",
                lock,
            ]
        )
    ).assert_success()
    lock_file = assert_lock_single(lock, "both", "1", is_source=True)
    assert SortedTuple([ProjectName("both")]) == lock_file.only_builds
    assert SortedTuple() == lock_file.only_wheels

    run_pex3(*(["lock", "update"] + repo_args + ["-R", "both", "--indent", "2", lock]))
    lock_file = assert_lock_single(lock, "both", "2", is_source=True)
    assert SortedTuple([ProjectName("both")]) == lock_file.only_builds
    assert SortedTuple() == lock_file.only_wheels


def test_only_wheel_honored_lock(
    tmpdir,  # type: Any
    repo_args,  # type: List[str]
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        *(
            [
                "lock",
                "create",
            ]
            + repo_args
            + [
                "--style",
                "universal",
                "--only-wheel",
                "both",
                "both>1",
                "--indent",
                "2",
                "-o",
                lock,
            ]
        )
    ).assert_success()
    lock_file = assert_lock_single(lock, "both", "2", is_source=False)
    assert SortedTuple() == lock_file.only_builds
    assert SortedTuple([ProjectName("both")]) == lock_file.only_wheels

    run_pex3(*(["lock", "update"] + repo_args + ["-R", "both<2", "--indent", "2", lock]))
    lock_file = assert_lock_single(lock, "both", "1", is_source=False)
    assert SortedTuple() == lock_file.only_builds
    assert SortedTuple([ProjectName("both")]) == lock_file.only_wheels
