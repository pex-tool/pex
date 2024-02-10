# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

import pytest

from pex.common import is_exe
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(
    not any(
        is_exe(os.path.join(entry, "docker"))
        for entry in os.environ.get("PATH", os.path.defpath).split(os.pathsep)
    ),
    reason="This test needs docker to run.",
)
def test_ssl_context(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    with open(os.path.join(str(tmpdir), "Dockerfile"), "w") as fp:
        fp.write(
            dedent(
                r"""
                FROM fedora:37
                
                ARG PBS_RELEASE
                ARG PBS_ARCHIVE
                
                RUN \
                curl --fail -sSL -O $PBS_RELEASE/$PBS_ARCHIVE && \
                curl --fail -sSL -O $PBS_RELEASE/$PBS_ARCHIVE.sha256 && \
                [[ \
                    "$(cat $PBS_ARCHIVE.sha256)" == "$(sha256sum $PBS_ARCHIVE | cut -d' ' -f1)" \
                ]] && \
                tar -xzf $PBS_ARCHIVE
                """
            )
        )

    pbs_release = "https://github.com/indygreg/python-build-standalone/releases/download/20240107"
    pbs_archive = "cpython-3.9.18+20240107-x86_64-unknown-linux-gnu-install_only.tar.gz"
    subprocess.check_call(
        args=[
            "docker",
            "build",
            "-t",
            "test_issue_2355",
            "--build-arg",
            "PBS_RELEASE={pbs_release}".format(pbs_release=pbs_release),
            "--build-arg",
            "PBS_ARCHIVE={pbs_archive}".format(pbs_archive=pbs_archive),
            str(tmpdir),
        ]
    )

    work_dir = os.path.join(str(tmpdir), "work_dir")
    os.mkdir(work_dir)
    subprocess.check_call(
        args=[
            "docker",
            "run",
            "--rm",
            "-v",
            "{pex_project_dir}:/code".format(pex_project_dir=pex_project_dir),
            "-v",
            "{work_dir}:/work".format(work_dir=work_dir),
            "-w",
            "/code",
            "test_issue_2355",
            "/python/bin/python3.9",
            "-mpex.cli",
            "lock",
            "create",
            "--style",
            "universal",
            "cowsay==5.0",
            "--indent",
            "2",
            "-o",
            "/work/lock.json",
        ]
    )

    result = run_pex_command(
        args=["--lock", os.path.join(work_dir, "lock.json"), "-c", "cowsay", "--", "Moo!"]
    )
    result.assert_success()
    assert "Moo!" in result.error
