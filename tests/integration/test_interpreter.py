# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess
import sys

from pex.compatibility import commonpath
from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from testing import PY310, ensure_python_interpreter, run_pex_command

if TYPE_CHECKING:
    from typing import Any


def test_boot_identification_leak(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")

    def assert_no_isolated_leak(python):
        # type: (str) -> None
        with ENV.patch(PEX_ROOT=pex_root), PythonInterpreter._cleared_memory_cache():
            interpreter = PythonInterpreter.from_binary(python)
            assert not any(
                pex_root == commonpath((pex_root, entry)) for entry in interpreter.sys_path
            ), (
                "The cached interpreter info for {python} contains leaked entries:\n"
                "{entries}".format(python=python, entries="\n".join(interpreter.sys_path))
            )

    empty_pex = os.path.join(str(tmpdir), "empty.pex")
    run_pex_command(
        args=["--pex-root", pex_root, "--runtime-pex-root", pex_root, "-o", empty_pex],
        python=sys.executable,
    ).assert_success()
    assert_no_isolated_leak(sys.executable)

    subprocess.check_call(args=[sys.executable, empty_pex, "-c", ""])
    assert_no_isolated_leak(sys.executable)

    other_python = ensure_python_interpreter(PY310)
    subprocess.check_call(args=[other_python, empty_pex, "-c", ""])
    # N.B.: Prior to the fix, this test failed with a vendored attrs leak:
    # E           AssertionError: The cached interpreter info for /home/jsirois/.pex_dev/pyenv/versions/3.10.7/bin/python3.10 contains leaked entries:
    # E             /tmp/pytest-of-jsirois/pytest-10/test_boot_identification_leak0/pex_root/isolated/975c556eea71292a09d930db2ca41875066d8be6/pex/vendor/_vendored/attrs
    # E             /home/jsirois/.pex_dev/pyenv/versions/3.10.7/lib/python310.zip
    # E             /home/jsirois/.pex_dev/pyenv/versions/3.10.7/lib/python3.10
    # E             /home/jsirois/.pex_dev/pyenv/versions/3.10.7/lib/python3.10/lib-dynload
    # E             /home/jsirois/.pex_dev/pyenv/versions/3.10.7/lib/python3.10/site-packages
    # E           assert not True
    # E            +  where True = any(<generator object test_boot_identification_leak.<locals>.assert_no_isolated_leak.<locals>.<genexpr> at 0x7fa5d084bc40>)
    assert_no_isolated_leak(other_python)
