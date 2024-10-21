# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

from pex.build_system.pep_517 import build_sdist
from pex.common import touch
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.result import Error
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from pex.version import __version__
from testing import make_project
from testing.build_system import assert_build_sdist, hatchling_only_supports_37_and_greater

if TYPE_CHECKING:
    from typing import Any


def test_build_sdist_project_directory_dne(tmpdir):
    # type: (Any) -> None

    project_dir = os.path.join(str(tmpdir), "project_dir")
    dist_dir = os.path.join(str(tmpdir), "dists")
    result = build_sdist(
        project_dir,
        dist_dir,
        LocalInterpreter.create(),
        ConfiguredResolver.default(),
    )
    assert isinstance(result, Error)
    assert str(result).startswith(
        "Project directory {project_dir} does not exist.".format(project_dir=project_dir)
    )


def test_build_sdist_project_directory_is_file(tmpdir):
    # type: (Any) -> None

    project_dir = os.path.join(str(tmpdir), "project_dir")
    touch(project_dir)
    dist_dir = os.path.join(str(tmpdir), "dists")
    result = build_sdist(
        project_dir,
        dist_dir,
        LocalInterpreter.create(),
        ConfiguredResolver.default(),
    )
    assert isinstance(result, Error)
    assert str(result).startswith(
        "Project directory {project_dir} is not a directory.".format(project_dir=project_dir)
    )


def test_build_sdist_setup_py(tmpdir):
    # type: (Any) -> None

    with make_project(name="foo", version="42") as project_dir:
        assert_build_sdist(project_dir, "foo", "42", tmpdir)


@hatchling_only_supports_37_and_greater
def test_build_sdist_pyproject_toml(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    assert_build_sdist(pex_project_dir, "pex", __version__, tmpdir)
