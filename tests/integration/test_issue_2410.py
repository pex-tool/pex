# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess
from textwrap import dedent

from colors import colors  # vendor:skip

from pex.common import safe_open
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_pex_with_editable(tmpdir):
    # type: (Any) -> None

    project_dir = os.path.join(str(tmpdir), "project")
    with safe_open(os.path.join(project_dir, "example.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import colors


                def colorize(*messages):
                    return colors.green(" ".join(messages))


                if __name__ == "__main__":
                    print(colorize(*sys.argv[1:]))
                    sys.exit(0)
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup(
                    name="example",
                    version="0.1.0",
                    py_modules=["example"],
                )
                """
            )
        )

    requirements = os.path.join(project_dir, "requirements.txt")
    with safe_open(requirements, "w") as fp:
        fp.write(
            dedent(
                """\
                ansicolors==1.1.8
                -e file://{project_dir}
                """
            ).format(project_dir=project_dir)
        )

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["-r", requirements, "-m", "example", "-o", pex]).assert_success()
    output = (
        subprocess.check_output(args=[pex, "A", "wet", "duck", "flies", "at", "night!"])
        .decode("utf-8")
        .strip()
    )
    assert colors.green("A wet duck flies at night!") == output, output
