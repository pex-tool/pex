# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

import pytest

from pex.compatibility import PY3
from pex.testing import PY38, ensure_python_interpreter, run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List


@pytest.mark.parametrize(
    ["boot_args"],
    [
        pytest.param([], id="__main__.py boot"),
        pytest.param(["--sh-boot"], id="--sh-boot"),
    ],
)
def test_symlink_preserved_in_argv0(
    tmpdir,  # type: Any
    boot_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "speak.pex")
    run_pex_command(
        args=["conscript==0.1.5", "cowsay==5.0", "fortune==1.1.0", "-c", "conscript", "-o", pex]
        + boot_args
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

    # N.B.: This fortune implementation uses print(..., file=...) without
    # `from __future__ import print_function`; so fails under Python 2.7 despite the fact its
    # released as a py2.py3 wheel.
    python = sys.executable if PY3 else ensure_python_interpreter(PY38)
    assert (
        "Just the one"
        == subprocess.check_output(args=[python, fortune, fortune_file]).decode("utf-8").strip()
    )
