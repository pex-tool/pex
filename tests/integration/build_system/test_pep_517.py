# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess
from typing import Callable

import pytest

from pex.build_system.testing import assert_build_sdist
from pex.testing import PY_VER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    PY_VER < (3, 7), reason="This version of Poetry only supports Python 3.7 and greater."
)
def test_build_sdist_pyproject_toml(
    tmpdir,  # type: Any
    clone,  # type: Callable[[str, str], str]
):
    # type: (...) -> None

    # The Poetry backend is important to supprt and the Poetry project dogfoods itself in its build.
    project_dir = clone(
        "https://github.com/python-poetry/poetry",
        "8cb3aab3d0eaf5a25b3cf57e0cfc633231774524",
    )
    assert_build_sdist(project_dir, "poetry", "1.2.0-beta.2.dev0", tmpdir)


def test_build_sdist_setup_py(
    tmpdir,  # type: Any
    clone,  # type: Callable[[str, str], str]
):
    # type: (...) -> None

    # This is an old setup.py based project that spews interfering output to stdout.
    project_dir = clone(
        "https://github.com/wickman/pystachio", "43acf709464e47ab0f40b26ec3b9dbbdb4e2ef12"
    )
    assert_build_sdist(project_dir, "pystachio", "0.8.10", tmpdir)
