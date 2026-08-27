# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import subprocess
from textwrap import dedent

import colors  # vendor:skip

from pex.common import safe_open
from testing import WheelBuilder, make_env, run_pex_command
from testing.pytest_utils.tmp import Tempdir


def test_intransitive_auto_ignores_errors(tmpdir):
    # type: (Tempdir) -> None

    requirements_pex = tmpdir.join("requirements.pex")
    run_pex_command(args=["ansicolors==1.1.8", "cowsay<6", "-o", requirements_pex]).assert_success()

    project_dir = tmpdir.join("project")
    with safe_open(os.path.join(project_dir, "color_moo.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import colors
                import cowsay


                def run():
                    cowsay.tux(colors.cyan(" ".join(sys.argv[1:])))
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup()
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = color-moo
                version = 0.1.0

                [options]
                py_modules = color_moo
                install_requires =
                    ansicolors
                    cowsay

                [options.entry_points]
                console_scripts =
                    moo = color_moo:run
                """
            )
        )
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )

    local_wheel = WheelBuilder(project_dir, wheel_dir=tmpdir.join("dist")).bdist()

    local_pex = tmpdir.join("local.pex")
    run_pex_command(
        args=[local_wheel, "--intransitive", "-c", "moo", "-o", local_pex]
    ).assert_success()

    cmd = [local_pex, "Moo?"]
    process = subprocess.Popen(args=cmd, stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    assert process.returncode != 0
    assert re.match(b".*Error: No module named '?colors'?.*", stderr, re.DOTALL)

    assert "| {msg} |".format(msg=colors.cyan("Moo?")) in subprocess.check_output(
        args=cmd, env=make_env(PEX_PATH=requirements_pex)
    ).decode("utf-8")
