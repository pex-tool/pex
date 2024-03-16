# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
from textwrap import dedent

from testing.docker import DockerVirtualenvRunner


def test_installed_wheels(fedora39_virtualenv_runner):
    # type: (DockerVirtualenvRunner) -> None

    assert {
        "ansicolors==1.1.8": "/virtualenv.venv/lib/python3.12/site-packages",
        "numpy==1.26.4": "/virtualenv.venv/lib64/python3.12/site-packages",
    } == json.loads(
        fedora39_virtualenv_runner.run(
            dedent(
                """\
                import json
                import subprocess
                import sys

                from pex.venv.virtualenv import Virtualenv


                subprocess.check_call(
                    args=[
                        sys.executable,
                        "-m",
                        "pex.cli",
                        "venv",
                        "create",
                        "-d",
                        "/virtualenv.venv",
                        "ansicolors==1.1.8",
                        "numpy==1.26.4"
                    ],
                    stdout=sys.stderr
                )

                venv = Virtualenv("/virtualenv.venv")
                json.dump(
                    {
                        str(dist.as_requirement()): dist.location
                        for dist in venv.iter_distributions()
                        if str(dist.metadata.project_name) in ("ansicolors", "numpy")
                    },
                    sys.stdout
                )
                """
            )
        ).decode("utf-8")
    )


def test_wheel_files(fedora39_virtualenv_runner):
    # type: (DockerVirtualenvRunner) -> None

    assert {
        "ansicolors==1.1.7": "/virtualenv.venv/lib/python3.12/site-packages",
        "numpy==1.26.3": "/virtualenv.venv/lib64/python3.12/site-packages",
    } == json.loads(
        fedora39_virtualenv_runner.run(
            dedent(
                """\
                import glob
                import json
                import subprocess
                import sys

                from pex.interpreter import PythonInterpreter
                from pex.pep_427 import install_wheel_interpreter
                from pex.venv.virtualenv import Virtualenv


                subprocess.check_call(
                    args=[
                        sys.executable,
                        "-m",
                        "pip",
                        "wheel",
                        "-w",
                        "/wheels",
                        "ansicolors==1.1.7",
                        "numpy==1.26.3"
                    ],
                    stdout=sys.stderr
                )

                interpreter = PythonInterpreter.get()
                for wheel_path in glob.glob("/wheels/*.whl"):
                    install_wheel_interpreter(wheel_path=wheel_path, interpreter=interpreter)

                venv = Virtualenv("/virtualenv.venv")
                json.dump(
                    {
                        str(dist.as_requirement()): dist.location
                        for dist in venv.iter_distributions()
                        if str(dist.metadata.project_name) in ("ansicolors", "numpy")
                    },
                    sys.stdout
                )
                """
            )
        ).decode("utf-8")
    )
