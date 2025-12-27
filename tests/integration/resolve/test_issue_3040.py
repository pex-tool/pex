# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
import sys

from pex.common import safe_mkdir
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pip.installation import get_pip
from pex.pip.version import PipVersion
from pex.resolve.configured_resolver import ConfiguredResolver
from testing import PY311, PY_VER, ensure_python_interpreter
from testing.docker import skip_unless_docker
from testing.pytest_utils.tmp import Tempdir


@skip_unless_docker
def test_pip_bootstrap_respects_pip_configuration(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    find_links = tmpdir.join("find-links")

    if PY_VER < (3, 11):
        interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY311))
        python_version = (3, 11)
    else:
        interpreter = PythonInterpreter.get()
        python_version = interpreter.version[:2]
    image = "python:{major}.{minor}".format(major=python_version[0], minor=python_version[1])
    if sys.version_info.releaselevel != "final":
        image += "-rc"

    pip_version = PipVersion.latest_compatible(
        Version("{major}.{minor}".format(major=python_version[0], minor=python_version[1]))
    )
    assert pip_version is not PipVersion.VENDORED, "Expected testing bootstrap of non-vendored Pip."

    requirements = ["cowsay<6"]
    requirements.extend(str(req) for req in pip_version.requirements)

    get_pip(
        interpreter=interpreter, resolver=ConfiguredResolver.version(pip_version=pip_version)
    ).spawn_build_wheels(requirements, wheel_dir=find_links).wait()

    dist = safe_mkdir(tmpdir.join("dist"))
    subprocess.check_call(
        args=[
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            "{pex_project_dir}:/code".format(pex_project_dir=pex_project_dir),
            "-w",
            "/code",
            "-v",
            "{find_links}:/find-links".format(find_links=find_links),
            "-v",
            "{dist}:/dist".format(dist=dist),
            image,
            "python",
            "-m",
            "pex",
            "--no-pypi",
            "-f",
            "/find-links",
            "--pip-version",
            str(pip_version),
            "cowsay",
            "-c",
            "cowsay",
            "-o",
            "/dist/pex",
        ]
    )
    assert b"| Moo! |" in subprocess.check_output(args=[os.path.join(dist, "pex"), "Moo!"])
