# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import shutil
import subprocess

import pytest

from pex.dist_metadata import Distribution
from pex.pep_503 import ProjectName
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InvalidVirtualenvError, Virtualenv
from testing import VenvFactory, all_python_venvs

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
    # type: (Virtualenv) -> Dict[ProjectName, Distribution]
    return {dist.metadata.project_name: dist for dist in venv.iter_distributions(rescan=True)}


def test_iter_distributions_setuptools_not_leaked(tmpdir):
    # type: (Any) -> None

    empty_venv_dir = os.path.join(str(tmpdir), "empty.venv")
    empty_venv = Virtualenv.create(venv_dir=empty_venv_dir)
    dists = index_distributions(empty_venv)
    assert ProjectName("setuptools") not in dists


@pytest.mark.parametrize(
    "venv_factory",
    [
        pytest.param(venv_factory, id=venv_factory.python_version)
        for venv_factory in all_python_venvs()
    ],
)
def test_iter_distributions(venv_factory):
    # type: (VenvFactory) -> None

    python, pip = venv_factory.create_venv()
    venv = Virtualenv.enclosing(python)
    assert venv is not None

    dists = index_distributions(venv)
    pip_dist = dists.get(ProjectName("pip"))
    assert pip_dist is not None, "Expected venv to have Pip installed."
    assert os.path.realpath(venv.site_packages_dir) == os.path.realpath(pip_dist.location)
    assert ProjectName("cowsay") not in dists

    subprocess.check_call(args=[pip, "install", "cowsay==4.0"])
    dists = index_distributions(venv)
    cowsay_dist = dists.get(ProjectName("cowsay"))
    assert cowsay_dist is not None, "Expected venv to have cowsay installed."
    assert "4.0" == cowsay_dist.version
    assert os.path.realpath(venv.site_packages_dir) == os.path.realpath(cowsay_dist.location)


def test_iter_distributions_spaces(tmpdir):
    # type: (Any) -> None

    venv_dir = os.path.join(str(tmpdir), "face palm")
    venv = Virtualenv.create(venv_dir=venv_dir)
    dists = index_distributions(venv)
    pip_dist = dists.get(ProjectName("pip"))
    assert pip_dist is None, "Expected venv to not have Pip installed."

    venv.install_pip()
    dists = index_distributions(venv)
    pip_dist = dists.get(ProjectName("pip"))
    assert pip_dist is not None, "Expected venv to have Pip installed."
    assert os.path.realpath(venv.site_packages_dir) == os.path.realpath(pip_dist.location)
