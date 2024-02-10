# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os.path

import pytest

from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import Artifact, FileArtifact, LockStyle, TargetSystem
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.resolved_requirement import Pin
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING
from testing import IntegResults, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Iterable, List, Set


@pytest.mark.parametrize(
    "style",
    [str(lock_style) for lock_style in LockStyle.values() if lock_style is not LockStyle.UNIVERSAL],
)
def test_non_universal_target_system_unsupported(style):
    # type: (str) -> None

    result = run_pex3("lock", "create", "--style", style, "--target-system", "linux", "ansicolors")
    result.assert_failure()
    assert (
        "The --target-system option only applies to --style {universal} locks.\n".format(
            universal=LockStyle.UNIVERSAL
        )
        == result.error
    )


def run_lock(
    lock_file,  # type: str
    extra_args,  # type: Iterable[str]
    *target_systems  # type: TargetSystem.Value
):
    # type: (...) -> IntegResults
    args = ["lock", "create", "--style", "universal", "-o", lock_file, "--indent", "2"]
    for target_system in target_systems:
        args.extend(("--target-system", str(target_system)))
    args.extend(extra_args)
    return run_pex3(*args)


def lock(
    tmpdir,  # type: Any
    extra_args,  # type: Iterable[str]
    *target_systems  # type: TargetSystem.Value
):
    # type: (...) -> Lockfile

    lock_file = os.path.join(
        str(tmpdir),
        "lock{id}.json".format(
            id="-{}".format("-".join(map(str, target_systems))) if target_systems else ""
        ),
    )
    run_lock(lock_file, extra_args, *target_systems).assert_success()
    return json_codec.load(lock_file)


def assert_file_artifact(artifact):
    # type: (Artifact) -> FileArtifact
    assert isinstance(artifact, FileArtifact)
    return artifact


def assert_wheel(artifact):
    # type: (Artifact) -> FileArtifact
    assert artifact.url.is_wheel
    return assert_file_artifact(artifact)


def test_target_system_universal(tmpdir):
    # type: (Any) -> None

    target_systems_powerset = sorted(
        itertools.chain.from_iterable(
            itertools.combinations(TargetSystem.values(), radix)
            for radix in range(len(TargetSystem.values()) + 1)
        )
    )
    locks = [
        lock(tmpdir, ["ansicolors==1.1.8"], *target_systems)
        for target_systems in target_systems_powerset
    ]
    assert len(locks) == len(target_systems_powerset)

    unique_resolves = set(lockfile.locked_resolves for lockfile in locks)
    assert 1 == len(unique_resolves), "Expected all resolves to be identical."

    assert 1 == len(locks[0].locked_resolves)
    locked_resolve = locks[0].locked_resolves[0]

    assert 1 == len(locked_resolve.locked_requirements)
    locked_requirement = locked_resolve.locked_requirements[0]

    assert Pin(ProjectName("ansicolors"), Version("1.1.8")) == locked_requirement.pin
    assert_wheel(locked_requirement.artifact)

    assert 1 == len(
        locked_requirement.additional_artifacts
    ), "Expected one additional source artifact."
    additional_artifact = locked_requirement.additional_artifacts[0]
    assert assert_file_artifact(additional_artifact).is_source


def test_target_system_platform_specific(
    tmpdir,  # type: Any
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    # The lineup of psutil 5.9.1 artifacts compatible with CPython==3.10.* out on PyPI is:
    # psutil-5.9.1.tar.gz
    # psutil-5.9.1-cp310-cp310-win_amd64.whl
    # psutil-5.9.1-cp310-cp310-win32.whl
    # psutil-5.9.1-cp310-cp310-manylinux_2_12_x86_64.manylinux2010_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl
    # psutil-5.9.1-cp310-cp310-manylinux_2_12_i686.manylinux2010_i686.manylinux_2_17_i686.manylinux2014_i686.whl
    # psutil-5.9.1-cp310-cp310-macosx_10_9_x86_64.whl
    #
    # There are additional artifacts for CPython 2.7 and 3.{6,7,8,9}

    def assert_expected_artifacts(
        expected_wheel_count,  # type: int
        *target_systems  # type: TargetSystem.Value
    ):
        # type: (...) -> Set[FileArtifact]

        lockfile = lock(
            tmpdir,
            [
                "--python-path",
                py310.binary,
                "--interpreter-constraint",
                "CPython==3.10.*",
                "psutil==5.9.1",
            ],
            *target_systems
        )

        assert 1 == len(lockfile.locked_resolves)
        locked_resolve = lockfile.locked_resolves[0]

        assert 1 == len(locked_resolve.locked_requirements)
        locked_requirement = locked_resolve.locked_requirements[0]

        assert Pin(ProjectName("psutil"), Version("5.9.1")) == locked_requirement.pin

        wheel_artifacts = set()  # type: Set[FileArtifact]
        sdist_artifacts = []  # type: List[FileArtifact]
        wheel_artifacts.add(assert_wheel(locked_requirement.artifact))
        for additional_artifact in locked_requirement.additional_artifacts:
            file_artifact = assert_file_artifact(additional_artifact)
            if file_artifact.is_source:
                sdist_artifacts.append(file_artifact)
            else:
                wheel_artifacts.add(assert_wheel(file_artifact))
        assert 1 == len(sdist_artifacts), "Expected one additional artifact to be the sdist."
        assert expected_wheel_count == len(wheel_artifacts)
        return wheel_artifacts

    linux_wheels = assert_expected_artifacts(2, TargetSystem.LINUX)
    mac_wheels = assert_expected_artifacts(1, TargetSystem.MAC)
    windows_wheels = assert_expected_artifacts(2, TargetSystem.WINDOWS)

    linux_and_mac_wheels = assert_expected_artifacts(3, TargetSystem.LINUX, TargetSystem.MAC)
    assert linux_wheels | mac_wheels == linux_and_mac_wheels

    linux_and_mac_and_windows_wheels = assert_expected_artifacts(
        5, TargetSystem.LINUX, TargetSystem.MAC, TargetSystem.WINDOWS
    )
    assert linux_wheels | mac_wheels | windows_wheels == linux_and_mac_and_windows_wheels

    assert linux_and_mac_and_windows_wheels == assert_expected_artifacts(5)


def test_issue_1821(
    tmpdir,  # type: Any
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    target_options = [
        "--python-path",
        py310.binary,
        "--interpreter-constraint",
        "CPython>=3.10,<4",
    ]

    args = target_options + [
        "--style",
        "universal",
        "--resolver-version",
        "pip-2020-resolver",
        "cryptography==36.0.2",
        "docker==5.0.3",
    ]

    # This lock solution requires pywin32 227 for windows, but that is a wheel-only distribution
    # with no wheels published for CPython 3.10 (see: https://pypi.org/project/pywin32/227/#files);
    # so, without restricting the target operating systems for the lock, we expect failure.
    result = run_lock(os.path.join(str(tmpdir), "lock"), args)
    result.assert_failure()
    assert (
        "ERROR: Could not find a version that satisfies the requirement "
        'pywin32==227; sys_platform == "win32" (from docker)'
    ) in result.error
    assert (
        'ERROR: No matching distribution found for pywin32==227; sys_platform == "win32"'
    ) in result.error

    lockfile = lock(tmpdir, args, TargetSystem.LINUX, TargetSystem.MAC)
    assert SortedTuple((TargetSystem.LINUX, TargetSystem.MAC)) == lockfile.target_systems
    assert lockfile.source is not None
    run_pex_command(
        args=["--lock", lockfile.source, "--", "-c", "import docker"], python=py310.binary
    ).assert_success()

    # Check that lock updates respect target systems.
    update_args = ["lock", "update"] + target_options + ["--dry-run", "check", lockfile.source]
    run_pex3(*update_args).assert_success()
