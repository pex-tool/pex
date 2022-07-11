# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
from textwrap import dedent

from colors import crossed, red

from pex.common import safe_open
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_requirements_pex(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    requirements_pex = os.path.join(str(tmpdir), "requirements.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "ansicolors==1.1.8",
            "-o",
            requirements_pex,
        ]
    ).assert_success()

    src_dir = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src_dir, "exe.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from colors import crossed, red


                print(red(crossed("Broken")))
                """
            )
        )

    app_pex = os.path.join(str(tmpdir), "app.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--requirements-pex",
            requirements_pex,
            "-D",
            src_dir,
            "-m",
            "exe",
            "-o",
            app_pex,
        ]
    ).assert_success()

    assert red(crossed("Broken")) == subprocess.check_output(args=[app_pex]).decode("utf-8").strip()
