# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from textwrap import dedent

from pex.typing import TYPE_CHECKING
from testing import IS_X86_64, run_pex_command
from testing.docker import skip_unless_docker

if TYPE_CHECKING:
    from typing import Any


@skip_unless_docker
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

                {extra_instructions}

                RUN \
                curl --fail -sSL -O $PBS_RELEASE/$PBS_ARCHIVE && \
                curl --fail -sSL -O $PBS_RELEASE/$PBS_ARCHIVE.sha256 && \
                [[ \
                    "$(cat $PBS_ARCHIVE.sha256)" == "$(sha256sum $PBS_ARCHIVE | cut -d' ' -f1)" \
                ]] && \
                tar -xzf $PBS_ARCHIVE
                """
            ).format(
                extra_instructions="\n".join(
                    # Git is needed for the git VCS URL the patched Pip needed for Python 3.13
                    # pre-releases is resolved by.
                    # TODO(John sirois): Remove once a Pip with Python 3.13 support is released:
                    #   https://github.com/pex-tool/pex/issues/2406
                    ["RUN dnf install -y git"]
                    if sys.version_info[:2] == (3, 13)
                    else []
                )
            )
        )

    pbs_release = "https://github.com/indygreg/python-build-standalone/releases/download/20240107"
    pbs_archive = "cpython-3.9.18+20240107-{arch}-unknown-linux-gnu-install_only.tar.gz".format(
        arch="x86_64" if IS_X86_64 else "aarch64"
    )
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
            # This env var propagation is needed to support patched Pip 24.0 for Python 3.13
            # pre-release testing.
            # TODO(John sirois): Remove once a Pip with Python 3.13 support is released:
            #   https://github.com/pex-tool/pex/issues/2406
            "--env",
            "_PEX_PIP_VERSION",
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
