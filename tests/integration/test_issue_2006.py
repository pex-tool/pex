# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess

from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def test_packaging(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "speak.pex")
    run_pex_command(
        args=["conscript==0.1.5", "cowsay==5.0", "fortune==1.1.0", "-c", "conscript", "-o", pex]
    ).assert_success()

    assert (
        "5.0" == subprocess.check_output(args=[pex, "cowsay", "--version"]).decode("utf-8").strip()
    )

    cowsay = os.path.join(str(tmpdir), "cowsay")
    os.symlink(pex, cowsay)
    assert "5.0" == subprocess.check_output(args=[cowsay, "--version"]).decode("utf-8").strip()

    fortune_file = os.path.join(str(tmpdir), "fortunes.txt")
    with open(fortune_file, "w") as fp:
        fp.write("Just the one")
    fortune = os.path.join(str(tmpdir), "fortune")
    os.symlink(pex, fortune)
    assert (
        "Just the one"
        == subprocess.check_output(args=[fortune, fortune_file]).decode("utf-8").strip()
    )
