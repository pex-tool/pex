# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from textwrap import dedent

from pex.common import safe_open
from pex.testing import IntegResults, run_pex_command
from pex.tools.commands.virtualenv import Virtualenv
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def run_pex_tools(*args):
    # type: (*str) -> IntegResults

    process = subprocess.Popen(
        args=[sys.executable, "-mpex.tools"] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    return IntegResults(
        output=stdout.decode("utf-8"), error=stderr.decode("utf-8"), return_code=process.returncode
    )


def test_collisions(
    tmpdir,  # type: Any
    pex_bdist,  # type: str
):
    # type: (...) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    collision_src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(collision_src, "will_not_collide_with_pex_module.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                def verb():
                  return 42
                """
            )
        )
    with safe_open(os.path.join(collision_src, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = collision
                version = 0.0.1

                [options]
                py_modules =
                    will_not_collide_with_pex_module
                
                [options.entry_points]
                # Although will_not_collide_with_pex_module does not collide with Pex, the 
                # generated bin/pex script will collide with the Pex pex script.
                console_scripts =
                    pex = will_not_collide_with_pex_module:verb
                """
            )
        )
    with safe_open(os.path.join(collision_src, "setup.py"), "w") as fp:
        fp.write("from setuptools import setup; setup()")

    collisions_pex = os.path.join(str(tmpdir), "collisions.pex")
    run_pex_command(
        args=[
            pex_bdist,
            collision_src,
            "-o",
            collisions_pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()

    venv_dir = os.path.join(str(tmpdir), "collisions.venv")
    result = run_pex_tools(collisions_pex, "venv", venv_dir)
    result.assert_failure()
    assert (
        "CollisionError: Encountered collision building venv at {venv_dir} "
        "from {pex}:\n"
        "1. {venv_dir}/bin/pex was provided by:".format(venv_dir=venv_dir, pex=collisions_pex)
    ) in result.error

    result = run_pex_tools(collisions_pex, "venv", "--collisions-ok", "--force", venv_dir)
    result.assert_success()
    assert (
        "PEXWarning: Encountered collision building venv at {venv_dir} from {pex}:\n"
        "1. {venv_dir}/bin/pex was provided by:".format(venv_dir=venv_dir, pex=collisions_pex)
    ) in result.error
    assert 42 == subprocess.call(args=[Virtualenv(venv_dir=venv_dir).bin_path("pex")])


def test_collisions_mergeable_issue_1570(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["opencensus==0.8.0", "opencensus_context==0.1.2", "-o", pex])

    venv_dir = os.path.join(str(tmpdir), "venv")
    run_pex_tools(pex, "venv", venv_dir).assert_success()

    venv = Virtualenv(venv_dir=venv_dir)
    _, stdout, _ = venv.interpreter.execute(
        args=[
            "-c",
            dedent(
                """\
                from __future__ import print_function

                import opencensus
                import opencensus.common


                print(opencensus.__file__)
                print(opencensus.common.__file__)
                """
            ),
        ]
    )
    assert [
        os.path.join(venv.site_packages_dir, "opencensus", "__init__.py"),
        os.path.join(venv.site_packages_dir, "opencensus", "common", "__init__.py"),
    ] == stdout.splitlines()
