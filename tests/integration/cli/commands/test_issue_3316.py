# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
from textwrap import dedent

import pytest

from pex.common import safe_mkdir, safe_open
from pex.pep_503 import ProjectName
from pex.resolve.lockfile.pep_751 import Pylock
from pex.result import try_
from pex.third_party.packaging.markers import Marker
from pex.typing import TYPE_CHECKING
from testing import WheelBuilder
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import List, Optional


class Wheel(object):
    def __init__(self, projects_dir):
        # type: (str) -> None
        self.projects_dir = projects_dir

    def __call__(
        self,
        dest_dir,  # type: str
        wheel_id,  # type: str
        wheel_tag,  # type: str
        dependencies,  # type: List[str]
    ):
        # type: (...) -> None

        project_dir = os.path.join(self.projects_dir, wheel_id)
        with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
            fp.write("from setuptools import setup; setup()")
        with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
            python_tag, platform_tag = wheel_tag.split("-none-")
            fp.write(
                dedent(
                    """\
                    [metadata]
                    name = pylock-repro-{wheel_id}
                    version = 1.0
                    
                    [options]
                    install_requires =
                        {install_requires}

                    [bdist_wheel]
                    plat-name = {platform_tag}
                    python-tag = {python_tag}
                    """
                ).format(
                    wheel_id=wheel_id,
                    install_requires="\n    ".join(dependencies),
                    platform_tag=platform_tag,
                    python_tag=python_tag,
                )
            )
        wheel_file = WheelBuilder(source_dir=project_dir).bdist()
        shutil.move(wheel_file, os.path.join(dest_dir, os.path.basename(wheel_file)))


@pytest.fixture
def wheel(tmpdir):
    # type: (Tempdir) -> Wheel
    return Wheel(tmpdir.join("projects"))


def test_split_universal_lock_pylock_export(
    tmpdir,  # type: Tempdir
    wheel,  # type: Wheel
):
    # type: (...) -> None

    find_links = safe_mkdir(tmpdir.join("find-links"))
    wheel(find_links, "a", "py3-none-any", ['pylock-repro-b; sys_platform == "linux"'])
    wheel(find_links, "b", "py3-none-any", ["pylock-repro-c", "pylock-repro-d"])
    wheel(find_links, "c", "py3-none-any", ["pylock-repro-d"])
    wheel(find_links, "d", "py3-none-manylinux_2_17_x86_64", [])

    lock = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--style",
        "universal",
        "--target-system",
        "linux",
        "--target-system",
        "linux",
        "--interpreter-constraint",
        ">=3.9",
        "-f",
        find_links,
        "--indent",
        "2",
        "-o",
        lock,
        "pylock-repro-a",
    ).assert_success()

    pylock_toml = tmpdir.join("pylock.toml")
    run_pex3("lock", "export", "--format", "pep-751", "-o", pylock_toml, lock).assert_success()

    pylock = try_(Pylock.parse(pylock_toml))
    packages_by_project_name = {package.project_name: package for package in pylock.packages}

    def assert_linux_marker(
        project_name,  # type: str
        expected_marker,  # type: Optional[Marker]
    ):
        # type: (...) -> None
        package = packages_by_project_name.pop(ProjectName(project_name))
        if expected_marker is None:
            assert package.marker is None
        else:
            assert package.marker is not None
            assert str(expected_marker) == str(package.marker)

    assert_linux_marker("pylock-repro-a", None)

    linux_marker = Marker('sys_platform == "linux"')
    assert_linux_marker("pylock-repro-b", linux_marker)
    assert_linux_marker("pylock-repro-c", linux_marker)
    assert_linux_marker("pylock-repro-d", linux_marker)

    assert not packages_by_project_name
