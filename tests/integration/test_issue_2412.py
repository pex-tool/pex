# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os.path
import subprocess
from textwrap import dedent

import pytest

import testing
from pex.common import safe_open
from pex.interpreter_constraints import InterpreterConstraint
from pex.pep_503 import ProjectName
from pex.requirements import PyPIRequirement, parse_requirement_file
from pex.resolve.lockfile import json_codec
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing.cli import run_pex3
from testing.lock import index_lock_artifacts

if TYPE_CHECKING:
    from typing import Any


def create_entry_module(project_dir):
    # type: (str) -> None

    with safe_open(os.path.join(project_dir, "entry.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                #!/usr/bin/env python3

                import numpy  # not used, just to illustrate a dependency


                def main():
                    print("Hello ", numpy.__version__)
                """
            )
        )


def create_setup_py(
    project_dir,  # type: str
    **setup_kwargs  # type: Any
):
    # type: (...) -> None

    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                #!/usr/bin/env python3

                import setuptools

                setuptools.setup(
                    name="repro",
                    version="0.0.1",
                    python_requires="~=3.9",
                    dependency_links=[],
                    entry_points={{
                        "console_scripts": [
                            "entry = entry:main",
                        ],
                    }},
                    py_modules=["entry"],
                    **{setup_kwargs!r}
                )
                """
            ).format(setup_kwargs=setup_kwargs)
        )


@pytest.fixture
def issue_2412_repro_project_dir(tmpdir):
    # type: (Any) -> str

    project_dir = os.path.join(str(tmpdir), "project")

    # This exactly replicates the project setup in the original problem repro repo in
    # https://github.com/pex-tool/pex/issues/2412 sans Makefile.
    create_entry_module(project_dir)
    input_requirements = os.path.join(project_dir, "requirements.in")
    with safe_open(input_requirements, "w") as fp:
        print("numpy", file=fp)
    create_setup_py(project_dir)
    return project_dir


def assert_bdist_pex(
    project_dir,  # type: str
    expected_numpy_version,  # type: str
):
    # type: (...) -> None

    assert "Hello  {numpy_version}\n".format(
        numpy_version=expected_numpy_version
    ) == subprocess.check_output(args=[os.path.join(project_dir, "dist", "entry")]).decode("utf-8")


skip_if_incompatible_with_repro_project = pytest.mark.skipif(
    not InterpreterConstraint.matches("CPython>=3.9,<3.13"),
    reason=(
        "The repro project under test requires Python ~=3.9 and we further restrict to CPython "
        "and place a version ceiling at 3.13 to ensure we resolve numpy wheels and do not need to "
        "build the sdist."
    ),
)


@skip_if_incompatible_with_repro_project
def test_bdist_pex_locked_issue_2412_repro_exact(
    issue_2412_repro_project_dir,  # type: str
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    venv = Virtualenv.create(
        venv_dir=os.path.join(issue_2412_repro_project_dir, ".env"),
        install_pip=InstallationChoice.UPGRADED,
        install_setuptools=InstallationChoice.UPGRADED,
    )
    subprocess.check_call(
        args=[venv.bin_path("pip"), "install", "-U", "pip-tools", pex_project_dir]
    )

    subprocess.check_call(
        args=[
            venv.bin_path("pip-compile"),
            "--output-file",
            "requirements.txt",
            "--generate-hashes",
            "requirements.in",
        ],
        cwd=issue_2412_repro_project_dir,
    )
    locked_requirements = list(
        parse_requirement_file(os.path.join(issue_2412_repro_project_dir, "requirements.txt"))
    )
    assert 1 == len(locked_requirements)

    locked_requirement = locked_requirements[0]
    assert isinstance(locked_requirement, PyPIRequirement)
    assert (
        "--hash=sha256:" in locked_requirement.line.raw_text
    ), "Expected the compiled requirements file to include hashes."

    locked_numpy_specifiers = list(locked_requirement.requirement.specifier)
    assert 1 == len(locked_numpy_specifiers)
    locked_numpy_specifier = locked_numpy_specifiers[0]
    assert "==" == locked_numpy_specifier.operator
    locked_numpy_version = locked_numpy_specifier.version

    subprocess.check_call(
        args=[
            venv.interpreter.binary,
            "setup.py",
            "bdist_pex",
            "--pex-args",
            "--disable-cache -vvvv -r requirements.txt --pip-version 24.0",
            "--bdist-all",
        ],
        cwd=issue_2412_repro_project_dir,
    )
    assert_bdist_pex(issue_2412_repro_project_dir, expected_numpy_version=locked_numpy_version)


def assert_bdist_pex_locked(
    project_dir,  # type: str
    lock,  # type: str
):
    # type: (...) -> None

    venv = Virtualenv.create(
        venv_dir=os.path.join(project_dir, ".env"),
        install_pip=InstallationChoice.YES,
        install_setuptools=InstallationChoice.YES,
    )
    subprocess.check_call(args=[venv.bin_path("pip"), "install", testing.pex_project_dir()])
    subprocess.check_call(
        args=[
            venv.interpreter.binary,
            "setup.py",
            "bdist_pex",
            "--pex-args",
            "--disable-cache -vvvv --lock {lock}".format(lock=lock),
            "--bdist-all",
        ],
        cwd=project_dir,
    )

    locked_numpy_version = index_lock_artifacts(json_codec.load(lock))[
        ProjectName("numpy")
    ].pin.version.raw
    assert_bdist_pex(project_dir=project_dir, expected_numpy_version=locked_numpy_version)


@skip_if_incompatible_with_repro_project
def test_bdist_pex_locked_issue_2412_repro_pex_lock(
    issue_2412_repro_project_dir,  # type: str
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    lock = os.path.join(issue_2412_repro_project_dir, "lock.json")
    run_pex3(
        "lock",
        "sync",
        "-r",
        os.path.join(issue_2412_repro_project_dir, "requirements.in"),
        "--pip-version",
        "24.0",
        "--style",
        "universal",
        "--interpreter-constraint",
        "~=3.9",
        "--indent",
        "2",
        "--lock",
        lock,
    ).assert_success()
    assert_bdist_pex_locked(project_dir=issue_2412_repro_project_dir, lock=lock)


@skip_if_incompatible_with_repro_project
def test_bdist_pex_locked_issue_2412_repro_pex_lock_inlined_requirements(
    tmpdir,  # type: str
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    project_dir = os.path.join(str(tmpdir), "project")
    create_entry_module(project_dir)
    create_setup_py(project_dir, install_requires=["numpy"])

    lock = os.path.join(project_dir, "lock.json")
    run_pex3(
        "lock",
        "sync",
        "--project",
        project_dir,
        "--pip-version",
        "24.0",
        "--style",
        "universal",
        "--interpreter-constraint",
        "~=3.9",
        "--indent",
        "2",
        "--lock",
        lock,
    ).assert_success()
    assert_bdist_pex_locked(project_dir=project_dir, lock=lock)
