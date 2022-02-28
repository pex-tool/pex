# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import shutil
import subprocess

import pytest

from pex.pep_503 import ProjectName
from pex.testing import ALL_PY_VERSIONS, ensure_python_venv
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import DistributionInfo, InvalidVirtualenvError, Virtualenv

if TYPE_CHECKING:
    from typing import Any, Dict


def test_invalid(tmpdir):
    # type: (Any) -> None

    with pytest.raises(InvalidVirtualenvError):
        Virtualenv(venv_dir=str(tmpdir))

    venv_dir = os.path.join(str(tmpdir), "venv")
    Virtualenv.create(venv_dir=venv_dir)
    venv = Virtualenv(venv_dir=venv_dir)

    shutil.rmtree(venv.site_packages_dir)
    with pytest.raises(InvalidVirtualenvError):
        Virtualenv(venv_dir=venv_dir)


def test_enclosing(tmpdir):
    # type: (Any) -> None

    venv_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir=venv_dir)

    enclosing = Virtualenv.enclosing(venv.interpreter)
    assert enclosing is not None
    assert venv_dir == enclosing.venv_dir

    enclosing = Virtualenv.enclosing(venv.interpreter.binary)
    assert enclosing is not None
    assert venv_dir == enclosing.venv_dir

    assert Virtualenv.enclosing(venv.interpreter.resolve_base_interpreter()) is None


def index_distributions(venv):
    # type: (Virtualenv) -> Dict[ProjectName, DistributionInfo]
    return {
        ProjectName(dist_info.project_name): dist_info for dist_info in venv.iter_distributions()
    }


def test_iter_distributions_setuptools_not_leaked(tmpdir):
    # type: (Any) -> None

    empty_venv_dir = os.path.join(str(tmpdir), "empty.venv")
    empty_venv = Virtualenv.create(venv_dir=empty_venv_dir)
    dists = index_distributions(empty_venv)
    assert ProjectName("setuptools") not in dists


@pytest.mark.parametrize("py_version", ALL_PY_VERSIONS)
def test_iter_distributions(
    tmpdir,  # type: Any
    py_version,  # type: str
):
    # type: (...) -> None

    python, pip = ensure_python_venv(py_version)

    venv = Virtualenv.enclosing(python)
    assert venv is not None

    dists = index_distributions(venv)
    pip_dist_info = dists.get(ProjectName("pip"))
    assert pip_dist_info is not None, "Expected venv to have Pip installed."
    assert os.path.realpath(venv.site_packages_dir) == os.path.realpath(
        pip_dist_info.sys_path_entry
    )
    assert ProjectName("cowsay") not in dists

    subprocess.check_call(args=[pip, "install", "cowsay==4.0"])
    dists = index_distributions(venv)
    cowsay_dist_info = dists.get(ProjectName("cowsay"))
    assert cowsay_dist_info is not None, "Expected venv to have cowsay installed."
    assert "4.0" == cowsay_dist_info.version
    assert os.path.realpath(venv.site_packages_dir) == os.path.realpath(
        cowsay_dist_info.sys_path_entry
    )


def test_iter_distributions_spaces(tmpdir):
    # type: (Any) -> None

    venv_dir = os.path.join(str(tmpdir), "face palm")
    venv = Virtualenv.create(venv_dir=venv_dir)
    dists = index_distributions(venv)
    pip_dist_info = dists.get(ProjectName("pip"))
    assert pip_dist_info is None, "Expected venv to not have Pip installed."

    venv.install_pip()
    dists = index_distributions(venv)
    pip_dist_info = dists.get(ProjectName("pip"))
    assert pip_dist_info is not None, "Expected venv to have Pip installed."
    assert os.path.realpath(venv.site_packages_dir) == os.path.realpath(
        pip_dist_info.sys_path_entry
    )
