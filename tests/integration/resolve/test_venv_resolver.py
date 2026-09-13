# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import json
import os.path
import re
import sys
from collections import defaultdict
from textwrap import dedent

import pytest

from pex.common import safe_copy, safe_mkdir, safe_open, safe_rmtree
from pex.dist_metadata import ProjectNameAndVersion
from pex.pep_425 import CompatibilityTags
from pex.pep_503 import ProjectName
from pex.pep_508 import MarkerEnvironment
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.targets import CompletePlatform
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import IS_LINUX, IS_PYPY, IntegResults, WheelBuilder, data, run_pex_command, subprocess
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir
from testing.uv import mark_skip_if_uv_not_supported

if TYPE_CHECKING:
    from typing import DefaultDict, Iterable, List, Tuple


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


@mark_skip_if_uv_not_supported
@pytest.mark.skipif(IS_PYPY, reason="This test uses CPython.")
def test_foreign_targets_uv(tmpdir):
    # type: (Tempdir) -> None

    def create_venv(
        venv_dir,  # type: str
        version_info,  # type: Tuple[int, int]
    ):
        # type: (...) -> None
        python_version = "{major}.{minor}".format(major=version_info[0], minor=version_info[1])
        subprocess.check_call(args=["uv", "venv", "--python", python_version, venv_dir])

    local_target_venv = tmpdir.join("local-venv")
    create_venv(venv_dir=local_target_venv, version_info=sys.version_info[:2])
    subprocess.check_call(
        args=["uv", "pip", "install", "--python", local_target_venv, "cowsay", "psutil"]
    )

    with open(
        data.path("platforms", "macos-aarch64.json" if IS_LINUX else "linux-x86_64.json")
    ) as fp:
        complete_platform = json.load(fp)
    foreign_platform = CompletePlatform.create(
        marker_environment=MarkerEnvironment(**complete_platform["marker_environment"]),
        supported_tags=CompatibilityTags.from_strings(complete_platform["compatible_tags"]),
    )
    assert foreign_platform.python_version is not None
    foreign_target_venv = tmpdir.join("foreign-venv")
    create_venv(venv_dir=foreign_target_venv, version_info=foreign_platform.python_version[:2])

    subprocess.check_call(
        args=[
            "uv",
            "pip",
            "install",
            "--python",
            foreign_target_venv,
            "--python-platform",
            "macos" if IS_LINUX else "linux",
            "cowsay",
            "psutil",
        ]
    )

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")

    def create_multiplatform_pex(*requirements):
        # type: (*str) -> IntegResults
        return run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--venv-repository",
                local_target_venv,
                "--venv-repository",
                foreign_target_venv,
                "--python",
                Virtualenv(local_target_venv).interpreter.binary,
                "--complete-platform",
                fp.name,
                "-o",
                pex,
            ]
            + list(requirements)
        )

    create_multiplatform_pex("cowsay", "psutil").assert_success()

    pex_info = PexInfo.from_pex(pex)
    distributions_by_project_name = defaultdict(list)  # type: DefaultDict[ProjectName, List[str]]
    for dist in pex_info.distributions:
        distributions_by_project_name[
            ProjectNameAndVersion.from_filename(dist).canonicalized_project_name
        ].append(dist)

    assert (
        len(distributions_by_project_name.pop(ProjectName("cowsay"))) == 1
    ), "The same cowsay wheel should have been picked for both targets."

    psutil_dists = distributions_by_project_name.pop(ProjectName("psutil"))
    assert len(psutil_dists) == 2, "Expected a platform-specific distribution for each target."
    assert any("linux" in dist for dist in psutil_dists)
    assert any("macos" in dist for dist in psutil_dists)

    assert not distributions_by_project_name

    process = subprocess.Popen(
        args=[
            pex,
            "-c",
            "import cowsay, psutil; cowsay.tux('Moo from ' + str(psutil.Process()))",
        ],
        stdout=subprocess.PIPE,
    )
    stdout, _ = process.communicate()
    assert process.returncode == 0
    assert "| Moo from psutil.Process(pid={pid}, ".format(pid=process.pid) in stdout.decode("utf-8")

    subprocess.check_call(
        args=["uv", "pip", "uninstall", "--python", foreign_target_venv, "psutil"]
    )
    create_multiplatform_pex("cowsay").assert_success()
    assert b"| Moo? |" in subprocess.check_output(
        args=[pex, "-c", "import cowsay; cowsay.tux('Moo?')"]
    )

    create_multiplatform_pex("cowsay", "psutil").assert_failure(
        expected_error_re=".*{msg}$".format(
            msg=re.escape(
                "Resolve from venv at {foreign_venv} failed: "
                "The virtual environment does not have psutil installed but it is required by top "
                "level requirement psutil".format(foreign_venv=foreign_target_venv)
            )
        ),
        re_flags=re.DOTALL,
    )
