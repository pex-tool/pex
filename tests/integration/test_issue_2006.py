# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import subprocess
import sys

import pytest

from pex.compatibility import PY3
from pex.typing import TYPE_CHECKING
from testing import PY38, ensure_python_interpreter, run_pex_command

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

    # N.B.: We use conscript (https://pypi.org/project/conscript/) here to test a very common real
    # use case for knowing the original path used to launch an executable. In general this allows
    # the executable to react differently based on its name. In the conscript case, it uses that
    # name to select a matching console script in the PEX if one exists and run that. If no such
    # match exists and there are no args, it launches a REPL session over the PEX contents.

    pex = os.path.join(str(tmpdir), "speak.pex")
    run_pex_command(
        args=["conscript==0.1.8", "cowsay==5.0", "fortune==1.1.0", "-c", "conscript", "-o", pex]
        + boot_args
    ).assert_success()

    assert (
        "5.0" == subprocess.check_output(args=[pex, "cowsay", "--version"]).decode("utf-8").strip()
    )

    cowsay = os.path.join(str(tmpdir), "cowsay")
    os.symlink(pex, cowsay)
    assert "5.0" == subprocess.check_output(args=[cowsay, "--version"]).decode("utf-8").strip(), (
        "Expected the symlink used to launch this PEX to be preserved in sys.argv[0] such that "
        "conscript could observe it and select the cowsay console script inside the PEX for"
        "execution. Without symlink preservation, the real PEX name of speak.pex will match no "
        "internal console scripts and the conscript entry point will drop into a REPL session over "
        "the PEX causing this test to hang waiting for a REPL session exit signal / command."
    )

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
