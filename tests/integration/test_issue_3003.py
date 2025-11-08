# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import json
import os.path
import shutil
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open, touch
from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.resolve.lockfile import json_codec
from pex.resolve.package_repository import PYPI
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import Virtualenv
from testing import make_env, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    import attr  # vendor:skip
else:
    from pex.third_party import attr


@pytest.fixture
def project_dir(tmpdir):
    # type: (Tempdir) -> str

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["uv_build>=0.9,<0.10.0"]
                build-backend = "uv_build"

                [project]
                name = "project"
                version = "0.42.0"
                description = "Repro of issue 3003"
                requires-python = "==3.10.*"
                dependencies = [
                    "opentelemetry-semantic-conventions==0.59b0",
                ]
                """
            )
        )
    touch(os.path.join(project_dir, "src", "project", "__init__.py"))
    return project_dir


@pytest.fixture
def project_venv(project_dir):
    # type: (str) -> Virtualenv

    subprocess.check_call(args=["uv", "sync"], cwd=project_dir)
    return Virtualenv(os.path.join(project_dir, ".venv"))


@attr.s(frozen=True)
class ProjectDistributions(object):
    sdist = attr.ib()  # type: str
    whl = attr.ib()  # type: str


@pytest.fixture
def project_distributions(
        project_dir,  # type: str
        tmpdir,  # type Tempdir
):
    # type: (...) -> ProjectDistributions

    dists_dir = tmpdir.join("dists")
    subprocess.check_call(args=["uv", "build", "-o", dists_dir], cwd=project_dir)

    sdists = glob.glob(os.path.join(dists_dir, "*.tar.gz"))
    assert 1 == len(sdists)

    whls = glob.glob(os.path.join(dists_dir, "*.whl"))
    assert 1 == len(whls)

    return ProjectDistributions(sdist=sdists[0], whl=whls[0])


@pytest.fixture
def project_sdist(project_distributions):
    # type: (ProjectDistributions) -> str
    return project_distributions.sdist


@pytest.fixture
def project_whl(project_distributions):
    # type: (ProjectDistributions) -> str
    return project_distributions.whl


@pytest.fixture(params=["project_dir", "project_sdist", "project_whl"])
def project(request):
    # type: (...) -> str
    return cast(str, request.getfixturevalue(request.param))


def assert_project(
        python,  # type: PythonInterpreter
        pex_root,  # type: str
        pex,  # type: str
):
    # type: (...) -> None

    output = (
        subprocess.check_output(
            args=[
                python.binary,
                pex,
                "-c",
                dedent(
                    """\
                import opentelemetry-semantic-conventions
                """
                ),
            ]
        )
        .decode("utf-8")
        .strip()
    )

    data = json.loads(output)
    assert pex_root == commonpath((pex_root, data["project_path"]))
    assert "0.42.0" == data["project_version"]
    assert pex_root == commonpath((pex_root, data["scipy_path"]))


def test_edge_case_semver_version_satisfied(
        tmpdir,  # type: Tempdir
        project,  # type: str
        project_venv,  # type: Virtualenv
        py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("project.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pip-version",
            "latest-compatible",
            "--venv-repository",
            project_venv.venv_dir,
            "project",
            "-o",
            pex,
            "--no-compress",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()

    if os.path.isdir(project):
        shutil.rmtree(project)
    else:
        os.unlink(project)
    assert_project(python=py310, pex_root=pex_root, pex=pex)


