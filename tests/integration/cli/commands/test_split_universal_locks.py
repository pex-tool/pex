# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
import subprocess
import sys
from collections import defaultdict
from textwrap import dedent

import pytest

from pex import resolver, targets
from pex.common import safe_mkdir, safe_open
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.pip.version import PipVersion
from pex.resolve.lockfile import json_codec
from pex.resolve.resolved_requirement import Pin
from pex.resolve.target_system import MarkerEnv, TargetSystem, UniversalTarget
from pex.typing import TYPE_CHECKING
from testing import PY27, PY311, WheelBuilder, ensure_python_interpreter, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import DefaultDict, List

    import colors  # vendor:skip
else:
    from pex.third_party import colors


@pytest.fixture
def split_requirements_lock(tmpdir):
    # type: (Tempdir) -> str
    pex_root = tmpdir.join("pex-root")
    lock_file = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--style",
        "universal",
        "cowsay<6; python_version < '3'",
        "cowsay==6; python_version >= '3'",
        "--indent",
        "2",
        "-o",
        lock_file,
    ).assert_success()

    lock = json_codec.load(lock_file)
    assert len(lock.locked_resolves) == 2
    assert len(lock.locked_resolves[0].locked_requirements) == 1
    assert len(lock.locked_resolves[1].locked_requirements) == 1

    versions_by_project_name = defaultdict(list)  # type: DefaultDict[ProjectName, List[Version]]
    for locked_resolve in lock.locked_resolves:
        for locked_requirement in locked_resolve.locked_requirements:
            versions_by_project_name[locked_requirement.pin.project_name].append(
                locked_requirement.pin.version
            )
    assert len(versions_by_project_name) == 1, "Should only have locked the cowsay project."
    locked_versions = versions_by_project_name.pop(ProjectName("cowsay"))
    assert [Version("5"), Version("6")] == sorted(locked_versions)

    return lock_file


PYTHON2 = sys.executable if sys.version_info[0] == 2 else ensure_python_interpreter(PY27)
PYTHON3 = sys.executable if sys.version_info[0] == 3 else ensure_python_interpreter(PY311)
PYTHON3_VERSION_STR = PythonInterpreter.from_binary(PYTHON3).python
PLATFORM_SYSTEM = targets.current().marker_environment.platform_system


def test_resolve_from_split_lock(
    tmpdir,  # type: Tempdir
    split_requirements_lock,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")

    def build_pex(python):
        # type: (str) -> None
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--lock",
                split_requirements_lock,
                "-c",
                "cowsay",
                "-o",
                pex,
            ],
            python=python,
        ).assert_success()

    build_pex(PYTHON2)
    assert b"| Moo! |" in subprocess.check_output(args=[PYTHON2, pex, "Moo!"])

    build_pex(PYTHON3)
    assert b"| Moo! |" in subprocess.check_output(args=[PYTHON3, pex, "-t", "Moo!"])


def test_export_from_split_lock(
    tmpdir,  # type: Tempdir
    split_requirements_lock,  # type: str
):
    # type: (...) -> None

    requirements = tmpdir.join("requirements.txt")

    def export_requirements(python):
        # type: (str) -> None
        run_pex3(
            "lock",
            "export",
            "--format",
            "pip",
            "-o",
            requirements,
            split_requirements_lock,
            python=python,
        ).assert_success()

    pylock = tmpdir.join("pylock.toml")

    def export_pylock(python):
        # type: (str) -> None
        run_pex3(
            "lock",
            "export",
            "--format",
            "pep-751",
            "-o",
            pylock,
            split_requirements_lock,
            python=python,
        ).assert_success()

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")

    def build_pex(
        python,  # type: str
        *extra_args  # type: str
    ):
        # type: (...) -> None
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "-c",
                "cowsay",
                "-o",
                pex,
            ]
            + list(extra_args),
            python=python,
        ).assert_success()

    export_requirements(PYTHON2)
    build_pex(PYTHON2, "-r", requirements)
    assert b"| Moo! |" in subprocess.check_output(args=[PYTHON2, pex, "Moo!"])

    export_pylock(PYTHON2)
    build_pex(PYTHON2, "--pylock", pylock)
    assert b"| Moo! |" in subprocess.check_output(args=[PYTHON2, pex, "Moo!"])

    export_requirements(PYTHON3)
    build_pex(PYTHON3, "-r", requirements)
    assert b"| Moo! |" in subprocess.check_output(args=[PYTHON3, pex, "-t", "Moo!"])

    export_pylock(PYTHON3)
    build_pex(PYTHON3, "--pylock", pylock)
    assert b"| Moo! |" in subprocess.check_output(args=[PYTHON3, pex, "-t", "Moo!"])


def ansicolors_asterisks(project_dir):
    # type: (str) -> str

    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup()
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = ansicolors
                version = 0.1.0

                [options]
                py_modules = colors

                [bdist_wheel]
                python_tag=py2.py3
                """
            )
        )
    with safe_open(os.path.join(project_dir, "colors.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                def green(text):
                    return "*** {text} ***".format(text=text)
                """
            )
        )
    return WheelBuilder(source_dir=project_dir).bdist()


@pytest.fixture
def find_links(tmpdir):
    # type: (Tempdir) -> str

    ansicolors_asterisks_wheel = ansicolors_asterisks(tmpdir.join("ansicolors-asterisks"))

    find_links_dir = safe_mkdir(tmpdir.join("find-links"))
    shutil.move(
        ansicolors_asterisks_wheel,
        os.path.join(find_links_dir, os.path.basename(ansicolors_asterisks_wheel)),
    )
    return find_links_dir


def test_split_repos_lock(
    tmpdir,  # type: Tempdir
    find_links,  # type: str
):
    # type: (...) -> None

    # N.B.: We need to make sure we have the Pip bootstrap we need when in pure find-links mode.
    if PipVersion.DEFAULT is PipVersion.VENDORED:
        requirements = [
            str(PipVersion.VENDORED.setuptools_requirement),
            str(PipVersion.VENDORED.wheel_requirement),
        ]
    else:
        requirements = list(map(str, PipVersion.DEFAULT.requirements))
    downloaded = resolver.download(requirements=requirements)
    for dist in downloaded.local_distributions:
        shutil.copy(dist.path, find_links)

    pex_root = tmpdir.join("pex-root")

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--find-links",
        "fl={find_links}".format(find_links=find_links),
        "--source",
        "fl=python_version == '{version}'".format(version=PYTHON3_VERSION_STR),
        "--style",
        "universal",
        "--indent",
        "2",
        "-o",
        lock,
        "ansicolors",
        "--pip-log",
        tmpdir.join("pip.log"),
    ).assert_success()

    pex = tmpdir.join("pex")

    def assert_split_resolve(
        python,  # type: str
        expected_message,  # type: str
    ):
        # type: (...) -> None
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--lock",
                lock,
                "-o",
                pex,
            ],
            python=python,
        ).assert_success()
        assert (
            expected_message
            == subprocess.check_output(
                args=[python, pex, "-c", "import colors; print(colors.green('Tom Bombadil'))"]
            )
            .decode("utf-8")
            .strip()
        )

    assert_split_resolve(PYTHON3, expected_message="*** Tom Bombadil ***")
    assert_split_resolve(PYTHON2, expected_message=colors.green("Tom Bombadil"))


def pin(
    project_name,  # type: str
    version,  # type: str
):
    # type: (...) -> Pin
    return Pin(ProjectName(project_name), Version(version))


def assert_expected_split_repos_and_requirements_lock(lock_file):
    # type: (str) -> None

    if sys.version_info.releaselevel != "final":
        # This test is complicated by Python development releases and is covered by several
        # production releases in CI; so we skip.
        return

    lock = json_codec.load(lock_file)
    # N.B.: We should have 4 locked resolves:
    foreign_os_no_find_links_in_play = frozenset([pin("ansicolors", "1.1.8")])
    expected_locks = {
        # 1. Find links for ansicolors in play.
        frozenset([pin("ansicolors", "0.1.0"), pin("cowsay", "6")]),
        # 2. No find links for ansicolors in play old cowsay
        frozenset([pin("ansicolors", "1.1.8"), pin("cowsay", "5")]),
        # 3. Foreign OS no cowsay no find links in play.
        foreign_os_no_find_links_in_play,
        # 4. Current OS no find links in play.
        frozenset([pin("ansicolors", "1.1.8"), pin("cowsay", "6")]),
    }
    current_system = MarkerEnv.create(
        extras=(), universal_target=UniversalTarget(systems=(TargetSystem.current(),))
    )
    for locked_resolve in lock.locked_resolves:
        pins = frozenset(
            locked_requirement.pin for locked_requirement in locked_resolve.locked_requirements
        )
        assert locked_resolve.marker
        if pins == foreign_os_no_find_links_in_play:
            assert not current_system.evaluate(locked_resolve.marker)
        else:
            assert current_system.evaluate(locked_resolve.marker)
        expected_locks.discard(pins)
    assert not expected_locks


def test_split_repos_and_requirements_lock(
    tmpdir,  # type: Tempdir
    find_links,  # type: str
    split_requirements_lock,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    lock_file = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--find-links",
        "fl={find_links}".format(find_links=find_links),
        "--source",
        "fl=ansicolors; python_version == '{version}'".format(version=PYTHON3_VERSION_STR),
        "--style",
        "universal",
        "--indent",
        "2",
        "-o",
        lock_file,
        "ansicolors<=1.1.8",
        "cowsay<6; python_version < '{version}' and platform_system == '{platform_system}'".format(
            version=PYTHON3_VERSION_STR, platform_system=PLATFORM_SYSTEM
        ),
        "cowsay==6; python_version >= '{version}'".format(version=PYTHON3_VERSION_STR),
        "--pip-log",
        tmpdir.join("pip.log"),
    ).assert_success()
    assert_expected_split_repos_and_requirements_lock(lock_file)

    pex = tmpdir.join("pex")

    def assert_split_resolve(
        python,  # type: str
        expected_message,  # type: str
        expected_ansicolors_version,  # type: str
        expected_cowsay_version,  # type, str
    ):
        # type: (...) -> None
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--lock",
                lock_file,
                "-o",
                pex,
            ],
            python=python,
        ).assert_success()
        assert (
            expected_message
            in subprocess.check_output(
                args=[
                    python,
                    pex,
                    "-c",
                    "import colors, cowsay; cowsay.tux(colors.green('Tom Bombadil'))",
                ]
            )
            .decode("utf-8")
            .strip()
        )
        assert {
            ProjectName("ansicolors"): Version(expected_ansicolors_version),
            ProjectName("cowsay"): Version(expected_cowsay_version),
        } == {
            distribution.metadata.project_name: distribution.metadata.version
            for distribution in PEX(
                pex, interpreter=PythonInterpreter.from_binary(python)
            ).resolve()
        }

    assert_split_resolve(
        PYTHON3,
        expected_message="| *** Tom Bombadil *** |",
        expected_ansicolors_version="0.1.0",
        expected_cowsay_version="6",
    )
    assert_split_resolve(
        PYTHON2,
        expected_message="| {msg} |".format(msg=colors.green("Tom Bombadil")),
        expected_ansicolors_version="1.1.8",
        expected_cowsay_version="5",
    )
