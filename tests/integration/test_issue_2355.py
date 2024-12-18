# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import os
import subprocess
from textwrap import dedent

from pex.interpreter import PythonInterpreter
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.pip.installation import compatible_version
from pex.pip.version import PipVersion
from pex.result import try_
from pex.targets import CompletePlatform, Targets
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

    pbs_release = "https://github.com/astral-sh/python-build-standalone/releases/download/20240107"
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

    docker_run_args = [
        "docker",
        "run",
        "--rm",
        "-v",
        "{pex_project_dir}:/code".format(pex_project_dir=pex_project_dir),
        "-w",
        "/code",
        "test_issue_2355",
        "/python/bin/python3.9",
        "-mpex.cli",
    ]
    complete_platform_data = json.loads(
        subprocess.check_output(
            args=docker_run_args + ["interpreter", "inspect", "--markers", "--tags"]
        )
    )
    container_interpreter = CompletePlatform.create(
        marker_environment=MarkerEnvironment(**complete_platform_data["marker_environment"]),
        supported_tags=CompatibilityTags.from_strings(complete_platform_data["compatible_tags"]),
    )
    pip_version = try_(
        compatible_version(
            targets=Targets(
                interpreters=tuple([PythonInterpreter.get()]),
                complete_platforms=tuple([container_interpreter]),
            ),
            requested_version=PipVersion.DEFAULT,
            context=__name__ + ".test_ssl_context",
        )
    )

    lock = os.path.join(str(tmpdir), "lock.json")
    with open(lock, "wb") as fp:
        fp.write(
            subprocess.check_output(
                args=docker_run_args
                + [
                    "lock",
                    "create",
                    "--pip-version",
                    str(pip_version),
                    "--style",
                    "universal",
                    "cowsay==5.0",
                    "--indent",
                    "2",
                ]
            )
        )

    result = run_pex_command(args=["--lock", lock, "-c", "cowsay", "--", "Moo!"])
    result.assert_success()
    assert "Moo!" in result.error
