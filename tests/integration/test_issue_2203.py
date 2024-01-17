# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import stat
import subprocess

from pex.common import safe_rmtree
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any


def test_read_only_venv(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    venv_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir)
    venv.install_pip(upgrade=True)
    subprocess.check_call(args=[venv.bin_path("pip"), "install", pex_project_dir])

    pex_root = os.path.join(str(tmpdir), "pex_root")

    def assert_pex_works():
        safe_rmtree(pex_root)
        assert (
            "Moo!"
            in subprocess.check_output(
                args=[
                    venv.bin_path("pex"),
                    "--pex-root",
                    pex_root,
                    "--runtime-pex-root",
                    pex_root,
                    "cowsay==5.0",
                    "-c",
                    "cowsay",
                    "--",
                    "Moo!",
                ]
            ).decode("utf-8")
        )

    assert_pex_works()

    write_mask = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    for root, dirs, files in os.walk(venv.site_packages_dir, topdown=False):
        for path in files + dirs:
            abs_path = os.path.join(root, path)
            os.chmod(abs_path, os.stat(abs_path).st_mode & ~write_mask)

    assert_pex_works()
