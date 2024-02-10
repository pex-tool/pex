# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import safe_open, safe_rmtree
from pex.layout import Layout
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.typing import TYPE_CHECKING
from testing import WheelBuilder, run_pex_command

if TYPE_CHECKING:
    from typing import Any, List


@pytest.fixture
def top_level_wheel(tmpdir):
    # type: (Any) -> str
    top_level_project = os.path.join(str(tmpdir), "project")
    with safe_open(os.path.join(top_level_project, "top_level", "__init__.py"), "w") as fp:
        fp.write("__path__ = __import__('pkgutil').extend_path(__path__, __name__)")
    with safe_open(os.path.join(top_level_project, "top_level", "lib.py"), "w") as fp:
        fp.write("OG = 'Henry Barber'")

    with safe_open(os.path.join(top_level_project, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = top_level
                version = 0.1.0

                [options]
                packages =
                    top_level
                """
            )
        )
    with safe_open(os.path.join(top_level_project, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )

    wheel_dir = os.path.join(str(tmpdir), "wheels")
    return WheelBuilder(source_dir=top_level_project, wheel_dir=wheel_dir).bdist()


@pytest.mark.parametrize(
    "style_args",
    [
        pytest.param([], id="zipapp"),
        pytest.param(["--venv"], id="venv (site-packages symlinks)"),
        pytest.param(["--venv", "--venv-site-packages-copies"], id="venv (site-packages copies)"),
    ],
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
def test_ns_package_split_across_sources_and_deps(
    tmpdir,  # type: Any
    top_level_wheel,  # type: str
    style_args,  # type: List[str]
    layout,  # type: Layout.Value
):
    # type: (...) -> None

    sources = os.path.join(str(tmpdir), "sources")
    with safe_open(os.path.join(sources, "top_level", "__init__.py"), "w") as fp:
        fp.write("__path__ = __import__('pkgutil').extend_path(__path__, __name__)")
    with safe_open(os.path.join(sources, "top_level", "mymain.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from top_level.lib import OG


                print("Hello {}!".format(OG))
                """
            )
        )

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex = os.path.join(str(tmpdir), "binary.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            top_level_wheel,
            "-D",
            sources,
            "-e",
            "top_level.mymain",
            "-o",
            pex,
            "--layout",
            layout.value,
        ]
        + style_args
    ).assert_success()

    safe_rmtree(pex_root)
    assert (
        "Hello Henry Barber!"
        == subprocess.check_output(args=[sys.executable, pex]).decode("utf-8").strip()
    )

    distributions = list(PEX(pex).resolve())
    assert 1 == len(distributions)

    top_level = distributions[0]
    assert ProjectName("top_level") == top_level.metadata.project_name
    assert Version("0.1.0") == top_level.metadata.version

    assert sorted(
        os.path.join(top_level.location, "top_level", expected)
        for expected in ("__init__.py", "lib.py")
    ) == sorted(
        os.path.join(root, f)
        for root, dirs, files in os.walk(top_level.location)
        for f in files
        if f.endswith(".py")
    ), (
        "Even in venv symlink mode, we expect the PEX 3rd-party wheel sources to remain isolated "
        "from the PEX user sources"
    )
