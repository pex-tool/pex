# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_mkdtemp
from pex.executables import chmod_plus_x, is_exe
from pex.typing import TYPE_CHECKING
from testing import pex_project_dir

if TYPE_CHECKING:
    from typing import Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


HAVE_DOCKER = any(
    is_exe(os.path.join(entry, "docker"))
    for entry in os.environ.get("PATH", os.path.defpath).split(os.pathsep)
)

skip_unless_docker = pytest.mark.skipif(not HAVE_DOCKER, reason="This test needs docker to run.")


@attr.s(frozen=True)
class DockerVirtualenvRunner(object):
    """Runs code in a venv created by Virtualenv at /virtualenv.venv in a docker container."""

    @classmethod
    def create(
        cls,
        base_image,  # type: str
        python="python",  # type: str
        virtualenv_version=None,  # type: Optional[str]
        tmpdir=None,  # type: Optional[str]
    ):
        # type: (...) -> DockerVirtualenvRunner

        test_script = os.path.join(tmpdir or safe_mkdtemp(), "test.sh")
        with open(test_script, "w") as fp:
            fp.write(
                dedent(
                    """\
                    #!/usr/bin/env bash

                    set -euo pipefail

                    {python} -mvenv /setup.venv >&2
                    /setup.venv/bin/pip install {virtualenv_requirement} >&2
                    /setup.venv/bin/virtualenv /virtualenv.venv >&2
                    PYTHONPATH=/code /virtualenv.venv/bin/python "$@"
                    """
                ).format(
                    python=python,
                    virtualenv_requirement=(
                        "virtualenv=={virtualenv_version}".format(
                            virtualenv_version=virtualenv_version
                        )
                        if virtualenv_version
                        else "virtualenv"
                    ),
                )
            )
        chmod_plus_x(test_script)

        return cls(base_image=base_image, test_script=test_script)

    base_image = attr.ib()  # type: str
    test_script = attr.ib()  # type: str

    def run(
        self,
        python_code,  # type: str
        *args  # type: str
    ):
        # type: (...) -> bytes

        if not HAVE_DOCKER:
            pytest.skip("This test needs docker to run.")

        return subprocess.check_output(
            args=[
                "docker",
                "run",
                "--rm",
                "-v",
                "{pex_project_dir}:/code".format(pex_project_dir=pex_project_dir()),
                "-v",
                "{test_script}:/test.sh".format(test_script=self.test_script),
                self.base_image,
                "/test.sh",
                "-c",
                python_code,
            ]
            + list(args)
        )
