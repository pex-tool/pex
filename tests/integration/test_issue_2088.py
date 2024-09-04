# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess
import sys

import pytest

from pex.cache.dirs import CacheDir
from pex.common import safe_rmtree
from pex.compatibility import commonpath
from pex.layout import Layout
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "symlink_site_packages",
    [
        pytest.param(True, id="--no-venv-site-packages-copies"),
        pytest.param(False, id="--venv-site-packages-copies"),
    ],
)
def test_venv_symlink_site_packages(
    tmpdir,  # type: Any
    layout,  # type: Layout.Value
    symlink_site_packages,  # type: bool
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    venv_site_packages_copies_arg = (
        "--no-venv-site-packages-copies" if symlink_site_packages else "--venv-site-packages-copies"
    )
    result = run_pex_command(
        args=[
            "ansicolors==1.1.8",
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--venv",
            venv_site_packages_copies_arg,
            "--layout",
            layout.value,
            "--seed",
            "-o",
            pex,
        ]
    )
    result.assert_success()
    venv_pex_path = str(result.output.strip())

    safe_rmtree(pex_root)
    colors_module_realpath = os.path.realpath(
        subprocess.check_output(
            args=[sys.executable, pex, "-c", "import colors; print(colors.__file__)"]
        )
        .decode("utf-8")
        .strip()
    )

    venv_dir = os.path.dirname(venv_pex_path)
    virtualenv = Virtualenv(venv_dir)
    site_packages_dir = os.path.realpath(virtualenv.site_packages_dir)

    ansicolors_venv_package_dir_realpath = os.path.join(site_packages_dir, "colors")
    assert os.path.isdir(ansicolors_venv_package_dir_realpath)

    symlinks_expected = symlink_site_packages and layout != Layout.LOOSE
    assert os.path.islink(ansicolors_venv_package_dir_realpath) == symlinks_expected

    if symlinks_expected:
        installed_wheels_dir_realpath = os.path.realpath(
            CacheDir.INSTALLED_WHEELS.path(pex_root=pex_root)
        )
        assert installed_wheels_dir_realpath == commonpath(
            (installed_wheels_dir_realpath, colors_module_realpath)
        )
    else:
        assert (
            os.path.join(ansicolors_venv_package_dir_realpath, "__init__.py")
            == colors_module_realpath
        )
