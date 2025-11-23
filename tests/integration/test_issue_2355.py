# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import json
import os
from textwrap import dedent

from pex.interpreter import PythonInterpreter
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.pip.installation import compatible_version
from pex.pip.version import PipVersion
from pex.result import try_
from pex.targets import CompletePlatform, Targets
from testing import IS_X86_64, run_pex_command, subprocess
from testing.docker import skip_unless_docker
from testing.pytest_utils.tmp import Tempdir


@skip_unless_docker
def test_ssl_context(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    dockerfile = tmpdir.join("Dockerfile")
    with open(dockerfile, "w") as dockerfile_fp:
        dockerfile_fp.write(
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
    tag = "test_issue_2355"

    def build_image():
        subprocess.check_call(
            args=[
                "docker",
                "build",
                "-t",
                tag,
                "--build-arg",
                "PBS_RELEASE={pbs_release}".format(pbs_release=pbs_release),
                "--build-arg",
                "PBS_ARCHIVE={pbs_archive}".format(pbs_archive=pbs_archive),
                str(tmpdir),
            ]
        )

    build_image()

    def docker_run_args(*extra_args):
        return (
            [
                "docker",
                "run",
                "--rm",
                "-v",
                "{pex_project_dir}:/code".format(pex_project_dir=pex_project_dir),
                "-w",
                "/code",
            ]
            + list(extra_args)
            + [
                tag,
                "/python/bin/python3.9",
                "-mpex.cli",
            ]
        )

    complete_platform_data = json.loads(
        subprocess.check_output(
            args=docker_run_args() + ["interpreter", "inspect", "--markers", "--tags"]
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
    pip_version_args = ["-e", "_PEX_PIP_VERSION={pip_version}".format(pip_version=pip_version)]
    if pip_version is PipVersion.ADHOC:
        for key, value in os.environ.items():
            if key.startswith("_PEX_PIP_ADHOC_"):
                pip_version_args.append("-e")
                pip_version_args.append("{key}={value}".format(key=key, value=value))

        # N.B.: We'll need git in the image, which is expensive; so we only add it for adhoc tests.
        with open(dockerfile, "a") as dockerfile_fp:
            print("RUN dnf -y install git", file=dockerfile_fp)
        tag = "test_issue_2355_adhoc"
        build_image()

    lock = tmpdir.join("lock.json")
    with open(lock, "wb") as lock_fp:
        lock_fp.write(
            subprocess.check_output(
                args=(
                    docker_run_args(*pip_version_args)
                    + [
                        "lock",
                        "create",
                        "--style",
                        "universal",
                        "cowsay==5.0",
                        "--indent",
                        "2",
                    ]
                )
            )
        )

    result = run_pex_command(args=["--lock", lock, "-c", "cowsay", "--", "Moo!"])
    result.assert_success()
    assert "Moo!" in result.error
