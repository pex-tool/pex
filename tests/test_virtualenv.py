# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex.common import touch
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing.pytest_utils.tmp import Tempdir


def test_local_pip_package(tmpdir):
    # type: (Tempdir) -> None

    cwd = tmpdir.join("chroot")
    touch(os.path.join(cwd, "pip", "__init__.py"))
    venv_dir = tmpdir.join("venv")

    venv = Virtualenv.create(venv_dir=venv_dir, cwd=cwd, install_pip=InstallationChoice.UPGRADED)
    venv.interpreter.execute(args=["-m", "pip", "-V"])
