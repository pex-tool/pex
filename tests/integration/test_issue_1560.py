# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess

import pytest

from pex.typing import TYPE_CHECKING
from testing import IntegResults, VenvFactory, all_python_venvs, make_source_dir, run_pex_command

if TYPE_CHECKING:
    from typing import Any

    import toml  # vendor:skip
else:
    from pex.third_party import toml


@pytest.mark.parametrize(
    "venv_factory",
    [
        pytest.param(venv_factory, id=venv_factory.python_version)
        for venv_factory in all_python_venvs()
    ],
)
def test_build_isolation(
    venv_factory,  # type: VenvFactory
    pex_project_dir,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None

    python, pip = venv_factory.create_venv()

    pyproject = toml.load(os.path.join(pex_project_dir, "pyproject.toml"))
    build_requirements = pyproject["build-system"]["requires"]
    assert len(build_requirements) > 0

    subprocess.check_call(args=[pip, "uninstall", "-y"] + build_requirements)
    result = run_pex_command(args=[pex_project_dir, "--no-build-isolation"], python=python)
    result.assert_failure()
    assert "ModuleNotFoundError: " in result.error, (
        "With build isolation turned off, it's expected that any build requirements "
        "(setuptools for Pex) are pre-installed. They are not; so we expect a failure here. Got:\n"
        "{error}".format(error=result.error)
    )

    subprocess.check_call(args=[pip, "install"] + build_requirements)

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[pex_project_dir, "--no-build-isolation", "-o", pex], python=python
    ).assert_success()
    subprocess.check_call(args=[python, pex, "-c", "import pex"])


def test_pep_517_for_pep_517_project():
    # type: () -> None

    # N.B.: The flit_core project has a PEP-517 build with no fallback to `setup.py`.

    def build_pex(*extra_args):
        # type: (*str) -> IntegResults
        return run_pex_command(
            args=["flit_core>=2,<4", "--no-wheel"] + list(extra_args) + ["--", "-c", "import pex"]
        )

    build_pex().assert_success()
    build_pex("--force-pep517").assert_success()

    result = build_pex("--no-use-pep517")
    result.assert_failure()
    assert (
        "ERROR: Disabling PEP 517 processing is invalid: project does not have a setup.py"
        in result.error
    )


def test_pep_517_for_legacy_project():
    # type: () -> None

    def assert_build_pex(*extra_args):
        # type: (*str) -> None
        with make_source_dir(name="project", version="0.1.0") as setup_py_project:
            run_pex_command(
                args=[setup_py_project] + list(extra_args) + ["--", "-c", "import project"]
            ).assert_success()

    assert_build_pex()
    assert_build_pex("--use-pep517")
    assert_build_pex("--no-use-pep517")
