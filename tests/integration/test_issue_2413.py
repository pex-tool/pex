# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os.path
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.executables import is_exe
from pex.pep_503 import ProjectName
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv

if TYPE_CHECKING:
    from typing import Any, List


def create_installation_choice_params(project_name):
    # type: (str) -> List[Any]
    return [
        pytest.param(
            installation_choice,
            id="{project_name}:{installation_choice}".format(
                project_name=project_name, installation_choice=installation_choice
            ),
        )
        for installation_choice in InstallationChoice.values()
    ]


@pytest.mark.parametrize("install_pip", create_installation_choice_params("pip"))
@pytest.mark.parametrize("install_setuptools", create_installation_choice_params("setuptools"))
@pytest.mark.parametrize("install_wheel", create_installation_choice_params("wheel"))
def test_venv_with_installs(
    tmpdir,  # type: Any
    install_pip,  # type: InstallationChoice.Value
    install_setuptools,  # type: InstallationChoice.Value
    install_wheel,  # type: InstallationChoice.Value
):
    # type: (...) -> None

    if install_pip is InstallationChoice.NO and (
        (install_setuptools is not InstallationChoice.NO)
        or (install_wheel is not InstallationChoice.NO)
    ):
        with pytest.raises(ValueError, match=r"^Installation of Pip is required in order to "):
            Virtualenv.create(
                str(tmpdir),
                install_pip=install_pip,
                install_setuptools=install_setuptools,
                install_wheel=install_wheel,
            )
        return

    venv = Virtualenv.create(
        str(tmpdir),
        install_pip=install_pip,
        install_setuptools=install_setuptools,
        install_wheel=install_wheel,
    )
    expected_projects = []
    if install_pip is not InstallationChoice.NO:
        expected_projects.append(ProjectName("pip"))
        # Pip gets installed with setuptools for Python < 3.12.
        if venv.interpreter.version[:2] < (3, 12):
            expected_projects.append(ProjectName("setuptools"))
    if install_setuptools is not InstallationChoice.NO:
        expected_projects.append(ProjectName("setuptools"))
    if install_wheel is not InstallationChoice.NO:
        expected_projects.append(ProjectName("wheel"))
    assert frozenset(expected_projects) == frozenset(
        dist.metadata.project_name for dist in venv.iter_distributions(rescan=True)
    )


def test_bdist_pex_under_tox(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    vend_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir=vend_dir, install_pip=InstallationChoice.YES)
    venv.interpreter.execute(args=["-m", "pip", "install", "tox"])
    tox = venv.bin_path("tox")
    assert is_exe(tox)

    project_dir = os.path.join(str(tmpdir), "project")
    with safe_open(os.path.join(project_dir, "entry.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import cowsay


                def main():
                    print(cowsay.__version__)
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import setuptools

                setuptools.setup(
                    name="repro",
                    version="0.0.1",
                    install_requires=["cowsay==5.0"],
                    entry_points={
                        "console_scripts": [
                            "entry = entry:main",
                        ],
                    },
                    py_modules=["entry"],
                )
                """
            )
        )
    with safe_open(os.path.join(project_dir, "tox.ini"), "w") as fp:
        fp.write(
            dedent(
                """\
                [testenv:bundle]
                passenv =
                    # This allows experimenting with Requires-Python metadata adjustment.
                    _PEX_REQUIRES_PYTHON
                deps =
                    setuptools
                    {pex}
                commands =
                    {{envpython}} setup.py bdist_pex \
                        --bdist-dir=dist --pex-args=--disable-cache --bdist-all
                """
            ).format(pex=pex_project_dir)
        )

    subprocess.check_call(args=[tox, "-e", "bundle"], cwd=project_dir)
    pexes = glob.glob(os.path.join(project_dir, "dist", "*"))
    assert 1 == len(pexes)

    pex = pexes[0]
    assert b"5.0\n" == subprocess.check_output(args=[pex])
