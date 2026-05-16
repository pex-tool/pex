# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os.path
from textwrap import dedent

import pytest

from pex.common import safe_copy, safe_mkdir, safe_open, safe_rmtree
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.typing import TYPE_CHECKING
from testing import WheelBuilder, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Iterable


def create_wheel(
    projects_dir,  # type: str
    wheel_dir,  # type: str
    project_name,  # type: str
    dependencies=(),  # type: Iterable[str]
):
    # type: (...) -> str

    project_dir = os.path.join(projects_dir, project_name)

    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        print("from setuptools import setup; setup()", file=fp)

    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = {name}
                version = 0.1.0
                
                [options]
                {install_requires}
                """
            ).format(
                name=project_name,
                install_requires="install_requires =\n  {deps}".format(
                    deps="\n  ".join(dependencies)
                )
                if dependencies
                else "",
            )
        )

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

    wheel = WheelBuilder(source_dir=project_dir).bdist()
    dst = os.path.join(wheel_dir, os.path.basename(wheel))
    safe_copy(wheel, dst)
    return dst


@pytest.fixture
def venv(tmpdir):
    # type: (Tempdir) -> str
    venv = tmpdir.join("venv")
    projects_dir = safe_mkdir(tmpdir.join("projects"))
    wheel_dir = safe_mkdir(tmpdir.join("wheels"))
    wheels = [
        create_wheel(
            projects_dir,
            wheel_dir,
            "a",
            dependencies=['b; extra == "x"', 'c; extra == "y"', 'd; extra == "z"'],
        ),
        create_wheel(projects_dir, wheel_dir, "b"),
        create_wheel(projects_dir, wheel_dir, "c"),
        create_wheel(projects_dir, wheel_dir, "d"),
        create_wheel(projects_dir, wheel_dir, "f", dependencies=["g"]),
        create_wheel(projects_dir, wheel_dir, "g", dependencies=["h[myextra]"]),
        create_wheel(projects_dir, wheel_dir, "h", dependencies=['i; extra == "myextra"']),
        create_wheel(projects_dir, wheel_dir, "i"),
        create_wheel(projects_dir, wheel_dir, "j", dependencies=["h"]),
    ]
    run_pex3("venv", "create", "--dest-dir", venv, *wheels).assert_success()
    return venv


def test_top_level_differing_extras(
    tmpdir,  # type: Tempdir
    venv,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")

    def assert_expected_resolve(*requirements):
        # type: (*str) -> None
        safe_rmtree(pex_root)
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--venv-repository",
                venv,
                "-o",
                pex,
            ]
            + list(requirements)
        ).assert_success()

        assert {ProjectName("a"), ProjectName("b"), ProjectName("d")} == set(
            dist.metadata.project_name for dist in PEX(pex).resolve()
        )

    assert_expected_resolve("a>=0.1.0", "a[x,z]")
    assert_expected_resolve("a[x,z]", "a>=0.1.0")


def test_transitive_differing_extras(
    tmpdir,  # type: Tempdir
    venv,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")

    def assert_expected_resolve(*requirements):
        # type: (*str) -> None
        safe_rmtree(pex_root)
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--venv-repository",
                venv,
                "-o",
                pex,
            ]
            + list(requirements)
        ).assert_success()
        assert {
            ProjectName("f"),
            ProjectName("g"),
            ProjectName("h"),
            ProjectName("i"),
            ProjectName("j"),
        } == set(dist.metadata.project_name for dist in PEX(pex).resolve())

    assert_expected_resolve("f", "j")
    assert_expected_resolve("j", "f")
