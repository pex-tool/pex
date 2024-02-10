# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
import subprocess
import sys

import pytest

from pex.interpreter import PythonInterpreter
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from pex.version import __version__
from testing import (
    PY27,
    PY310,
    ensure_python_interpreter,
    ensure_python_venv,
    make_env,
    run_pex_command,
)
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Optional


def test_no_python(tmpdir):
    # type: (Any) -> None

    result = run_pex3("venv", "inspect", str(tmpdir))
    result.assert_failure()
    assert result.error.startswith(
        "The virtualenv at {venv_dir} is not valid. Failed to load an interpreter ".format(
            venv_dir=tmpdir
        )
    )


def test_not_venv_interpreter(py310):
    # type: (PythonInterpreter) -> None

    result = run_pex3("venv", "inspect", py310.binary)
    result.assert_failure()
    assert (
        "{python} is not an venv interpreter.".format(python=py310.binary) == result.error.strip()
    )


def test_not_venv_dir(py310):
    # type: (PythonInterpreter) -> None

    result = run_pex3("venv", "inspect", py310.prefix)
    result.assert_failure()
    assert "{venv} is not a venv.".format(venv=py310.prefix) == result.error.strip()


def assert_inspect(
    target,  # type: str
    expected_venv_dir,  # type: str
    expected_system_site_packages,  # type: Optional[bool]
    expected_base_interpreter,  # type: PythonInterpreter
    expected_pex_provenance,  # type: bool
):
    # type: (...) -> Any

    result = run_pex3("venv", "inspect", target)
    result.assert_success()

    data = json.loads(result.output)
    assert os.path.realpath(expected_venv_dir) == os.path.realpath(data["venv_dir"])
    assert expected_system_site_packages == data["include_system_site_packages"]

    interpreter = data["interpreter"]
    assert expected_base_interpreter.binary == interpreter["base_binary"]
    assert ".".join(map(str, expected_base_interpreter.version)) == interpreter["version"]

    provenance = data["provenance"]
    assert provenance["is_pex"] is expected_pex_provenance
    assert __version__ if expected_pex_provenance else None == provenance["pex_version"]

    if expected_pex_provenance:
        expected_created_by = (
            "virtualenv {version}".format(version=Virtualenv.VIRTUALENV_VERSION)
            if sys.version_info[0] == 2
            else "venv"
        )
        assert expected_created_by == provenance["created_by"]

    return data


def test_inspect_pex_venv(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "cowsay.pex")
    run_pex_command(
        args=["--include-tools", "cowsay==5.0", "ansicolors==1.1.8", "-o", pex]
    ).assert_success()

    venv_dir = os.path.join(str(tmpdir), "venv")
    subprocess.check_call(args=[sys.executable, pex, "venv", venv_dir], env=make_env(PEX_TOOLS=1))

    current_base_interpreter = PythonInterpreter.get().resolve_base_interpreter()
    data1 = assert_inspect(
        target=venv_dir,
        expected_venv_dir=venv_dir,
        expected_system_site_packages=False,
        expected_base_interpreter=current_base_interpreter,
        expected_pex_provenance=True,
    )
    assert "cowsay" in data1["scripts"]
    assert ["ansicolors==1.1.8", "cowsay==5.0"] == data1["distributions"]

    data2 = assert_inspect(
        target=Virtualenv(venv_dir).interpreter.binary,
        expected_venv_dir=venv_dir,
        expected_system_site_packages=False,
        expected_base_interpreter=current_base_interpreter,
        expected_pex_provenance=True,
    )
    assert data1 == data2


@pytest.mark.parametrize("python_version", [PY27, PY310])
@pytest.mark.parametrize(
    "system_site_packages",
    [pytest.param(value, id="system_site_packages={}".format(value)) for value in (True, False)],
)
def test_inspect_venv_non_pex(
    python_version,  # type: str
    system_site_packages,  # type: bool
):
    # type: (...) -> None

    python, _ = ensure_python_venv(python_version, system_site_packages=system_site_packages)
    python_major_version = int(python_version.split(".")[0])
    assert_inspect(
        target=python,
        expected_venv_dir=os.path.dirname(os.path.dirname(python)),
        expected_system_site_packages=None if python_major_version == 2 else system_site_packages,
        expected_base_interpreter=PythonInterpreter.from_binary(
            ensure_python_interpreter(python_version)
        ),
        expected_pex_provenance=False,
    )


@pytest.mark.parametrize(
    "system_site_packages",
    [pytest.param(value, id="system_site_packages={}".format(value)) for value in (True, False)],
)
def test_inspect_venv_virtualenv(
    tmpdir,  # type: Any
    system_site_packages,  # type: bool
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "virtualenv.pex")
    run_pex_command(args=["virtualenv", "-c", "virtualenv", "-o", pex]).assert_success()
    dists = {dist.metadata.project_name: dist.metadata.version for dist in PEX(pex).resolve()}
    virtualenv_version = dists[ProjectName("virtualenv")]

    venv_dir = os.path.join(str(tmpdir), "venv")
    args = [sys.executable, pex, venv_dir]
    if system_site_packages:
        args.append("--system-site-packages")
    subprocess.check_call(args=args)

    data = assert_inspect(
        target=venv_dir,
        expected_venv_dir=venv_dir,
        expected_system_site_packages=system_site_packages,
        expected_base_interpreter=PythonInterpreter.get().resolve_base_interpreter(),
        expected_pex_provenance=False,
    )
    assert "pip" in data["scripts"]

    provenance = data["provenance"]
    assert "virtualenv {version}".format(version=virtualenv_version.raw) == provenance["created_by"]
