# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import stat
import subprocess
from collections import OrderedDict

from pex.common import safe_rmtree
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv

if TYPE_CHECKING:
    from typing import Any


def test_read_only_venv(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    venv_dir = os.path.join(str(tmpdir), "venv")
    venv = Virtualenv.create(venv_dir, install_pip=InstallationChoice.UPGRADED)
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
    orig_mode_by_path = OrderedDict()  # type: OrderedDict[str, int]
    for root, dirs, files in os.walk(venv.site_packages_dir, topdown=False):
        for path in files + dirs:
            abs_path = os.path.join(root, path)
            orig_mode = os.stat(abs_path).st_mode
            orig_mode_by_path[abs_path] = orig_mode
            os.chmod(abs_path, orig_mode & ~write_mask)
    try:
        assert_pex_works()
    finally:
        for path, mode in orig_mode_by_path.items():
            os.chmod(path, mode)
