# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from textwrap import dedent

import pytest
from colors import colors  # vendor:skip

from pex.typing import TYPE_CHECKING
from pex.version import __version__
from testing import IntegResults, run_pex_command

if TYPE_CHECKING:
    from typing import Any, List


# N.B.: To test that we are running a REPL we'll show that it computes result even after
# assertion errors and exceptions that would normally halt a script.
# To check that it forwards python options we use -O to deactivate asserts
# See: https://docs.python.org/3/using/cmdline.html#cmdoption-O
@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
    ],
)
def test_repl_python_options(
    execution_mode_args,  # type: List[str]
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex_command(
        args=[
            "ansicolors==1.1.8",
            "-o",
            pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--seed",
        ]
        + execution_mode_args
    ).assert_success()

    repl_commands = dedent(
        """
        import colors
        assert False
        raise Exception("customexc")
        result = 20 + 103
        print(colors.green("Worked: {}".format(result)))
        quit()
        """
    )

    def execute_pex(disable_assertions):
        # type: (bool) -> IntegResults
        args = [pex]
        if disable_assertions:
            args.append("-O")
        process = subprocess.Popen(
            args=args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(input=repl_commands.encode("utf-8"))
        return IntegResults(
            output=stdout.decode("utf-8"),
            error=stderr.decode("utf-8"),
            return_code=process.returncode,
        )

    expected_banner = dedent(
        """\
        Pex {pex_version} hermetic environment with 1 requirement and 1 activated distribution.
        Python {python_version} on {platform}
        Type "help", "pex", "copyright", "credits" or "license" for more information.
        """
    ).format(python_version=sys.version, platform=sys.platform, pex_version=__version__)

    # The assertion will fail and print but since it is a REPL it will keep going
    # and compute the result
    result = execute_pex(disable_assertions=False)
    result.assert_success()
    assert result.error.startswith(expected_banner), result.error
    assert "AssertionError" in result.error
    assert "customexc" in result.error
    assert colors.green("Worked: 123") in result.output

    # The -O will disable the assertion, but the regular exception will still get raised.
    result = execute_pex(disable_assertions=True)
    result.assert_success()
    assert result.error.startswith(expected_banner), result.error
    assert "AssertionError" not in result.error
    assert "customexc" in result.error
    assert colors.green("Worked: 123") in result.output
