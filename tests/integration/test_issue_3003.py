# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open, touch
from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from pex.venv.virtualenv import Virtualenv
from testing import make_env, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

OPEN_TELEMETRY_SEMANTIC_CONVENTIONS_BETA = "opentelemetry-semantic-conventions==0.59b0"


@pytest.fixture
def pex_root(tmpdir):
    # type: (Tempdir) -> str
    return tmpdir.join("pex-root")


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
                    "{opentelemetry_requirement}",
                ]
                """.format(
                    opentelemetry_requirement=OPEN_TELEMETRY_SEMANTIC_CONVENTIONS_BETA
                )
            )
        )
    touch(os.path.join(project_dir, "src", "project", "__init__.py"))
    return project_dir


@pytest.fixture
def project_venv(project_dir):
    # type: (str) -> Virtualenv

    subprocess.check_call(args=["uv", "sync"], cwd=project_dir)
    return Virtualenv(os.path.join(project_dir, ".venv"))


def assert_opentelemetry_semconv(
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
                "from opentelemetry import semconv; print(semconv.__file__)",
            ]
        )
        .decode("utf-8")
        .strip()
    )

    assert pex_root == commonpath((pex_root, output))


def test_edge_case_semver_version_satisfied_venv_repository(
    tmpdir,  # type: Tempdir
    pex_root,  # type: str
    project_venv,  # type: Virtualenv
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

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
    ).assert_failure(
        expected_error_re=r".*^{error_msg}$".format(
            error_msg=re.escape(
                "Resolve from venv at {venv_dir} failed: The virtual environment has "
                "opentelemetry-semantic-conventions 0.59b0 installed but it does not meet top "
                "level requirement project -> opentelemetry-semantic-conventions==0.59b0.".format(
                    venv_dir=project_venv.venv_dir
                )
            ),
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )

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
            "--pre",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()
    assert_opentelemetry_semconv(python=py310, pex_root=pex_root, pex=pex)

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
            OPEN_TELEMETRY_SEMANTIC_CONVENTIONS_BETA,
            "-o",
            pex,
            "--no-compress",
        ],
        python=project_venv.interpreter.binary,
    ).assert_success()
    assert_opentelemetry_semconv(python=py310, pex_root=pex_root, pex=pex)


@pytest.fixture
def pex_lock(
    project_dir,  # type: str
    pex_root,  # type: str
    py310,  # type: PythonInterpreter
):
    # type: (...) -> str

    lock = os.path.join(project_dir, "lock.json")
    run_pex3(
        "lock",
        "create",
        "--pex-root",
        pex_root,
        project_dir,
        "--indent",
        "2",
        "-o",
        lock,
        python=py310.binary,
    ).assert_success()
    return lock


@pytest.fixture
def pylock_toml(
    project_dir,  # type: str
    pex_root,  # type: str
    pex_lock,  # type: str
    py310,  # type: PythonInterpreter
):
    # type: (...) -> str

    pylock_toml = os.path.join(project_dir, "pylock.toml")
    run_pex3(
        "lock",
        "export",
        "--pex-root",
        pex_root,
        "--format",
        "pep-751",
        "-o",
        pylock_toml,
        pex_lock,
        python=py310.binary,
    ).assert_success()
    return pylock_toml


def test_edge_case_semver_version_satisfied_locks(
    tmpdir,  # type: Tempdir
    pex_root,  # type: str
    pex_lock,  # type: str
    pylock_toml,  # type: str
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex = tmpdir.join("project.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pylock",
            pylock_toml,
            OPEN_TELEMETRY_SEMANTIC_CONVENTIONS_BETA,
            "-o",
            pex,
            "--no-compress",
        ],
        python=py310.binary,
    ).assert_success()
    assert_opentelemetry_semconv(python=py310, pex_root=pex_root, pex=pex)

    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--lock",
            pex_lock,
            OPEN_TELEMETRY_SEMANTIC_CONVENTIONS_BETA,
            "-o",
            pex,
            "--no-compress",
        ],
        python=py310.binary,
    ).assert_success()
    assert_opentelemetry_semconv(python=py310, pex_root=pex_root, pex=pex)


@pytest.fixture
def repository_pex(
    tmpdir,  # type: Tempdir
    pex_root,  # type: str
    project_dir,  # type: str
    py310,  # type: PythonInterpreter
):
    repository_pex = tmpdir.join("repository.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--include-tools",
            project_dir,
            "-o",
            repository_pex,
        ],
        python=py310.binary,
    ).assert_success()
    return repository_pex


@pytest.fixture
def pre_resolved_dists(
    tmpdir,  # type: Tempdir
    pex_root,  # type: str
    repository_pex,  # type: str
    py310,  # type: PythonInterpreter
):
    # type: (...) -> str

    pre_resolved_dists = tmpdir.join("pre-resolved-dists")
    subprocess.check_call(
        args=[
            py310.binary,
            repository_pex,
            "repository",
            "extract",
            "--dest-dir",
            pre_resolved_dists,
        ],
        env=make_env(PEX_TOOLS=1),
    )
    return pre_resolved_dists


def test_edge_case_semver_version_satisfied_pex_repository(
    tmpdir,  # type: Tempdir
    pex_root,  # type: str
    repository_pex,  # type: str
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex = tmpdir.join("project.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pex-repository",
            repository_pex,
            OPEN_TELEMETRY_SEMANTIC_CONVENTIONS_BETA,
            "-o",
            pex,
            "--no-compress",
        ],
        python=py310.binary,
    ).assert_success()
    assert_opentelemetry_semconv(python=py310, pex_root=pex_root, pex=pex)


def test_edge_case_semver_version_satisfied_pre_resolved_dists(
    tmpdir,  # type: Tempdir
    pex_root,  # type: str
    pre_resolved_dists,  # type: str
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    pex = tmpdir.join("project.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pre-resolved-dists",
            pre_resolved_dists,
            OPEN_TELEMETRY_SEMANTIC_CONVENTIONS_BETA,
            "-o",
            pex,
            "--no-compress",
        ],
        python=py310.binary,
    ).assert_success()
    assert_opentelemetry_semconv(python=py310, pex_root=pex_root, pex=pex)
