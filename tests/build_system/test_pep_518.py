# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
from textwrap import dedent

from pex.build_system import pep_518
from pex.build_system.pep_518 import BuildSystem
from pex.common import touch
from pex.environment import PEXEnvironment
from pex.pep_503 import ProjectName
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.result import Error
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Optional, Union


def load_build_system(project_directory):
    # type: (...) -> Union[Optional[BuildSystem], Error]
    return pep_518.load_build_system(ConfiguredResolver.default(), project_directory)


def test_load_build_system_not_a_python_project(tmpdir):
    # type: (Any) -> None
    assert load_build_system(str(tmpdir)) is None


def test_load_build_system_setup_py(tmpdir):
    # type: (Any) -> None
    project_dir = str(tmpdir)
    touch(os.path.join(project_dir, "setup.py"))
    assert load_build_system(project_dir) is None


def test_load_build_system_pyproject_but_not_for_build(tmpdir):
    # type: (Any) -> None
    project_dir = str(tmpdir)
    pyproject_toml = os.path.join(project_dir, "pyproject.toml")
    touch(pyproject_toml)
    assert load_build_system(project_dir) is None

    with open(pyproject_toml, "w") as fp:
        fp.write(
            dedent(
                """\
                [tool.black]
                target_version = ["py35"]
                """
            )
        )
    assert load_build_system(project_dir) is None


def test_load_build_system_pyproject(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    build_system = load_build_system(pex_project_dir)
    assert isinstance(build_system, BuildSystem)
    assert "flit_core.buildapi" == build_system.build_backend
    dists = {
        dist.metadata.project_name for dist in PEXEnvironment.mount(build_system.pex).resolve()
    }
    assert ProjectName("flit_core") in dists
    subprocess.check_call(
        args=[build_system.pex, "-c", "import {}".format(build_system.build_backend)]
    )
