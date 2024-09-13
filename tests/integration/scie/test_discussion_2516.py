# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os.path
import subprocess
from textwrap import dedent

from pex.common import safe_open
from pex.scie import SciePlatform
from pex.typing import TYPE_CHECKING
from testing import make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any

    import colors  # vendor:skip
else:
    from pex.third_party import colors


def test_discussion_2516_op(tmpdir):
    # type: (Any) -> None

    requirements = os.path.join(str(tmpdir), "requirements-pex.txt")
    with open(requirements, "w") as fp:
        fp.write(
            dedent(
                """\
                ansicolors
                cowsay
                """
            )
        )

    with safe_open(os.path.join(str(tmpdir), "src", "ardia", "cli", "ardia.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import colors
                import cowsay


                def main() -> None:
                    message = " ".join(sys.argv[1:])
                    cowsay.tux(colors.cyan(message))
                """
            )
        )

    out_dir = os.path.join(str(tmpdir), "build", "pex")
    for abbreviated_platform in (
        "linux_aarch64-cp-3.11.9-cp311",
        "linux_x86_64-cp-3.11.9-cp311",
        "macosx_11_0_arm64-cp-3.11.9-cp311",
        "macosx_11_0_x86_64-cp-3.11.9-cp311",
    ):
        run_pex_command(
            args=[
                "--no-build",
                "--requirement",
                "requirements-pex.txt",
                "--entry-point",
                "ardia.cli.ardia:main",
                "--package",
                "ardia@src",
                "--output-file",
                os.path.join(out_dir, "ardia"),
                "--scie",
                "eager",
                "--scie-only",
                "--scie-name-style",
                "platform-parent-dir",
                "--platform",
                abbreviated_platform,
            ],
            cwd=str(tmpdir),
        ).assert_success()

    assert sorted(
        [
            "build/pex/linux-aarch64/ardia",
            "build/pex/linux-x86_64/ardia",
            "build/pex/macos-aarch64/ardia",
            "build/pex/macos-x86_64/ardia",
        ]
    ) == sorted(
        os.path.relpath(os.path.join(root, f), str(tmpdir))
        for root, _, files in os.walk(out_dir)
        for f in files
    )
    assert not glob.glob(
        os.path.join(str(tmpdir), "ardia*")
    ), "We expected no PEX or scie leaked in the CWD."

    native_scie = os.path.join(out_dir, SciePlatform.CURRENT.value, "ardia")
    output = subprocess.check_output(
        args=[native_scie, "Tux", "says", "Moo?"], env=make_env(PATH=None)
    ).decode("utf-8")
    assert "| {msg} |".format(msg=colors.cyan("Tux says Moo?")) in output, output
