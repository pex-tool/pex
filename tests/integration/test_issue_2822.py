# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
import sys
from os import mkdir
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.compatibility import commonpath
from pex.layout import Layout
from pex.typing import TYPE_CHECKING
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, Iterator, List


@pytest.fixture
def read_only_pex_root(tmpdir):
    # type: (Tempdir) -> Iterator[str]

    pex_root = tmpdir.join("readonly-pex-root")
    mkdir(pex_root)
    os.chmod(pex_root, 0o555)
    try:
        yield pex_root
    finally:
        os.chmod(pex_root, 0o755)


@pytest.fixture(params=["module", "script"])
def entry_point_args(
    tmpdir,  # type: Tempdir
    request,  # type: Any
):
    # type: (...) -> List[str]

    project = tmpdir.join("project")
    module = os.path.join(project, "module.py")
    with safe_open(module, "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import colors


                def print_colors_module_path():
                    print(colors.__file__)


                if __name__ == "__main__":
                    print_colors_module_path()
                    sys.exit(0)
                """
            )
        )

    if request.param == "module":
        return ["ansicolors==1.1.8", "--exe", module]

    with open(os.path.join(project, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
    with open(os.path.join(project, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = module
                version = 0.1.0

                [options]
                py_modules = module
                install_requires =
                    ansicolors==1.1.8

                [options.entry_points]
                console_scripts =
                    script = module:print_colors_module_path
                """
            )
        )
    with open(os.path.join(project, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup()
                """
            )
        )
    return [project, "-c", "script"]


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param(layout, id=layout.value)
        for layout in Layout.values()
        # N.B.: A loose layout PEX undergoes no extraction into the PEX_ROOT and so is not relevant
        # to this test.
        if layout is not Layout.LOOSE
    ],
)
@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--sh-boot"], id="SH_BOOT"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-SH_BOOT"),
    ],
)
def test_tmp_pex_root(
    tmpdir,  # type: Tempdir
    read_only_pex_root,  # type: str
    fake_system_tmp_dir,  # type: str
    layout,  # type: Layout.Value
    entry_point_args,  # type: List[str]
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    pex_root = tmpdir.join("pex-root")
    run_pex_command(
        args=[
            "-o",
            pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            read_only_pex_root,
            "--layout",
            layout.value,
        ]
        + entry_point_args
        + execution_mode_args
    ).assert_success()

    colors_module = subprocess.check_output(args=[sys.executable, pex]).decode("utf-8").strip()
    assert fake_system_tmp_dir == commonpath((fake_system_tmp_dir, colors_module))
    assert not os.path.exists(colors_module)
