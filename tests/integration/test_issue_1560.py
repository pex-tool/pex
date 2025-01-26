# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open, touch
from pex.typing import TYPE_CHECKING
from testing import IntegResults, VenvFactory, all_python_venvs, make_source_dir, run_pex_command
from testing.pytest.tmp import Tempdir
from testing.pythonPI import skip_flit_core_39

if TYPE_CHECKING:
    pass


@pytest.mark.parametrize(
    "venv_factory",
    [
        pytest.param(venv_factory, id=venv_factory.python_version)
        for venv_factory in all_python_venvs()
    ],
)
def test_build_isolation(
    venv_factory,  # type: VenvFactory
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None

    project_dir = tmpdir.join("project")
    build_requirements = ["flit_core"]
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = {build_requirements!r}
                build-backend = "flit_core.buildapi"

                [project]
                name = "foo"
                version = "0.0.1"
                description = "Quality bars."
                """
            ).format(build_requirements=build_requirements)
        )
    touch(os.path.join(project_dir, "foo.py"))

    python, pip = venv_factory.create_venv()
    # N.B.: Pip 25.0 introduces a new message to check for here.
    run_pex_command(args=[project_dir, "--no-build-isolation"], python=python).assert_failure(
        expected_error_re=r".*(?:{old_message}|{new_message}).*".format(
            old_message=re.escape("ModuleNotFoundError: No module named 'flit_core'"),
            new_message=re.escape("BackendUnavailable: Cannot import 'flit_core.buildapi'"),
        ),
        re_flags=re.DOTALL,
    )

    subprocess.check_call(args=[pip, "install"] + build_requirements)

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[project_dir, "--no-build-isolation", "-o", pex], python=python
    ).assert_success()
    subprocess.check_call(args=[python, pex, "-c", "import foo"])


@skip_flit_core_39
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
