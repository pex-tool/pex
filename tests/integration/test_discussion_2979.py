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
                description = "Repro of https://github.com/pex-tool/pex/discussions/2979"
                requires-python = "==3.10.*"
                dependencies = [
                    "anywidget<0.10.0,>=0.9.14",

                    # Internal only.
                    # "corr_module>=1.0.0",

                    # Because only marketdata<=0.2.0 is available and your project depends on marketdata>=2.0.0,<3.0.0, we can conclude that your project's requirements are unsatisfiable.
                    # "marketdata<3.0.0,>=2.0.0",
                    "marketdata",

                    "matplotlib<4.0.0,>=3.7.0",
                    "numpy<3.0.0,>=2.2.3",
                    "openpyxl<4.0.0,>=3.1.5",
                    "plotly<6.0.0,>=5.24.1",
                    "polars<2.0.0,>=1.32.3",
                    "pyyaml<7.0.0,>=6.0.2",
                    "scikit-learn<2.0.0,>=1.6.1",
                    "scipy<2.0.0,>=1.15.0",
                    "statsmodels<0.15.0,>=0.14.4",

                    # Because only tsm>=8.0 is available and your project depends on tsm>=2.0.11,<3.0.0, we can conclude that your project's requirements are unsatisfiable.
                    # "tsm<3.0.0,>=2.0.11",
                    "tsm",

                    # Internal only.
                    # "utils-internal==1.0.11"
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
                import json
                import sys
                from importlib import metadata

                import project
                import scipy


                json.dump(
                    {
                        "project_path": project.__file__,
                        "project_version": metadata.version("project"),
                        "scipy_path": scipy.__file__,
                    },
                    sys.stdout,
                )
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


def test_venv_subset_with_specifiers_discussion_op(
    tmpdir,  # type: Tempdir
    project,  # type: str
    project_venv,  # type: Virtualenv
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
            "scipy",
            "--project",
            project,
            "-o",
            pex,
            "--no-compress",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()

    assert_project(python=project_venv.interpreter, pex_root=pex_root, pex=pex)


def test_editable_installs_subset_issue_2982(
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


def test_editable_installs_full_resolve_issue_2982(
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


def test_lock_project(
    tmpdir,  # type: Tempdir
    project,  # type: str
    project_whl,  # type: str
    project_venv,  # type: Virtualenv
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    lock_file = tmpdir.join("lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        "--project",
        project,
        "--pip-version",
        "latest-compatible",
        "--indent",
        "2",
        "-o",
        lock_file,
        # This test has problems completing its resolve just using --devpi, so we ensure PyPI is
        # also used.
        "--use-pip-config",
        env=make_env(PIP_EXTRA_INDEX_URL=PYPI),
        python=project_venv.interpreter.binary,
    ).assert_success()
    lock = json_codec.load(lock_file)
    assert len(lock.locked_resolves) == 1
    locked_project_names = {
        locked_requirement.pin.project_name
        for locked_requirement in lock.locked_resolves[0].locked_requirements
    }

    pex = tmpdir.join("project-deps.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pip-version",
            "latest-compatible",
            "--project",
            project_whl,
            "--venv-repository",
            project_venv.venv_dir,
            "-o",
            pex,
            "--no-compress",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()

    assert locked_project_names == {
        distribution.metadata.project_name
        for distribution in PEX(pex, interpreter=project_venv.interpreter).resolve()
        if distribution.metadata.project_name != ProjectName("project")
    }
