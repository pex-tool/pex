# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Dict, Text


def create_venv(
    venv_dir,  # type: str
    *requirements  # type: str
):
    # type: (...) -> Virtualenv
    venv = Virtualenv.create(venv_dir, install_pip=InstallationChoice.YES)
    subprocess.check_call(args=[venv.interpreter.binary, "-mpip", "install"] + list(requirements))
    return venv


def index_venv(venv):
    # type: (Virtualenv) -> Dict[ProjectName, Version]
    return {
        dist.metadata.project_name: dist.metadata.version
        for dist in venv.iter_distributions(rescan=True)
    }


def test_same_wheel_resolved_from_multiple_venvs(tmpdir):
    # type: (Tempdir) -> None

    venv1 = create_venv(tmpdir.join("venv1"), "wheel")
    venv2 = create_venv(tmpdir.join("venv2"), "wheel")
    venv3 = create_venv(tmpdir.join("venv3"), "wheel")

    venv1_contents = index_venv(venv1)
    assert venv1_contents == index_venv(venv2)
    assert venv1_contents == index_venv(venv3)

    pex_root = tmpdir.join("pex-root")
    pex = tmpdir.join("pex")

    def assert_create_pex(venv):
        # type: (Virtualenv) -> Text

        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--venv-repository",
                venv.venv_dir,
                "-o",
                pex,
            ]
        ).assert_success()

        # N.B.: We take the dirname since wheel.__file__ will report the .pyc instead of the
        # .py after 1st use under Python 2.7.
        return os.path.dirname(
            subprocess.check_output(args=[pex, "-c", "import wheel; print(wheel.__file__)"])
            .decode("utf-8")
            .strip()
        )

    wheel1_path = assert_create_pex(venv1)
    assert wheel1_path == assert_create_pex(venv2)
    assert wheel1_path == assert_create_pex(venv3)
