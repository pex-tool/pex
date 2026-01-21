# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess

from testing.docker import skip_unless_docker
from testing.pytest_utils.tmp import Tempdir


@skip_unless_docker
def test_sdist_extraction(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    assert (
        b"/root/.cache/pex/installed_wheels/2/"
        b"f0e26292130d3efebe48e40b10c5f9e79911ad507ccd2f02aea5793dea67abc0/"
        b"pymongo-3.11.4-cp311-cp311-linux_x86_64.whl/pymongo/__init__.py\n"
    ) == subprocess.check_output(
        args=[
            "docker",
            "run",
            "--rm",
            "-v",
            "{code}:/code".format(code=pex_project_dir),
            "-w",
            "/code",
            "python:3.11.2-slim-bullseye",
            "bash",
            "-c",
            "python -mpex pymongo==3.11.4 -- -c 'import pymongo; print(pymongo.__file__)'",
        ]
    )
