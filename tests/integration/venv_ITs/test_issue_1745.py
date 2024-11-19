# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

import pytest
from colors import colors  # vendor:skip

from pex.common import safe_open
from pex.enum import Enum
from pex.typing import TYPE_CHECKING
from testing import IntegResults, run_pex_command

if TYPE_CHECKING:
    from typing import Any, List, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


# N.B.: To test that Python interpreter options are forwarded to Python we include an "assert False"
# in the code executed that we would normally expect to fail. Only by adding the `-O` option, which
# causes assertions to be ignored by Python, should the code execute fully without failing.
# See: https://docs.python.org/3/using/cmdline.html#cmdoption-O

CODE = dedent(
    """\
    import sys

    import colors


    assert False, colors.red("Failed")
    print(colors.green("Worked: {}".format(" ".join(sys.argv[1:]))))
    """
)


@attr.s(frozen=True)
class ExecutionConfiguration(object):
    args = attr.ib(factory=list)  # type: List[str]
    cwd = attr.ib(default=None)  # type: Optional[str]
    stdin = attr.ib(default=None)  # type: Optional[bytes]


class PythonInterfaceOption(Enum["PythonInterfaceOption.Value"]):
    class Value(Enum.Value):
        pass

    DASHC = Value("-c <code>")
    DASHM = Value("-m <module>")
    DASH = Value("- (<code> from STDIN)")
    FILE = Value("<python file>")
    DIRECTORY = Value("<dir>")


PythonInterfaceOption.seal()


@pytest.fixture
def execution_configuration(
    request,  # type: Any
    tmpdir,  # type: Any
):
    # type: (...) -> ExecutionConfiguration
    if request.param is PythonInterfaceOption.DASHC:
        return ExecutionConfiguration(args=["-c", CODE])

    if request.param is PythonInterfaceOption.DASH:
        return ExecutionConfiguration(args=["-"], stdin=CODE.encode("utf-8"))

    if request.param not in (
        PythonInterfaceOption.DASHM,
        PythonInterfaceOption.FILE,
        PythonInterfaceOption.DIRECTORY,
    ):
        raise AssertionError("Unexpected PythonInterfaceOption: {}".format(request.param))

    src = os.path.join(str(tmpdir), "src")
    python_file = os.path.join(
        src,
        "{filename}.py".format(
            filename="__main__" if request.param is PythonInterfaceOption.DIRECTORY else "module"
        ),
    )
    with safe_open(python_file, "w") as fp:
        fp.write(CODE)

    if request.param is PythonInterfaceOption.DASHM:
        return ExecutionConfiguration(args=["-m", "module"], cwd=src)

    if request.param is PythonInterfaceOption.FILE:
        return ExecutionConfiguration(args=[python_file])

    return ExecutionConfiguration(args=[src])


@pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="ZIPAPP"), pytest.param(["--venv"], id="VENV")]
)
@pytest.mark.parametrize(
    "execution_configuration",
    [pytest.param(value, id=str(value)) for value in PythonInterfaceOption.values()],
    indirect=True,
)
def test_interpreter_mode_python_options(
    execution_mode_args,  # type: List[str]
    execution_configuration,  # type: ExecutionConfiguration
    tmpdir,  # type: Any
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["ansicolors==1.1.8", "-o", pex] + execution_mode_args).assert_success()

    def execute_pex(disable_assertions):
        # type: (bool) -> IntegResults
        args = [pex]
        if disable_assertions:
            args.append("-O")
        args.extend(execution_configuration.args)
        args.extend(("program", "args"))
        process = subprocess.Popen(
            args=args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=execution_configuration.cwd,
        )
        stdout, stderr = process.communicate(input=execution_configuration.stdin)
        return IntegResults(
            output=stdout.decode("utf-8"),
            error=stderr.decode("utf-8"),
            return_code=process.returncode,
        )

    # With no `-O` for Python, the CODE assertion should fail.
    result = execute_pex(disable_assertions=False)
    result.assert_failure()
    assert colors.red("Failed") in result.error

    # But with `-O` forwarded to Python, the CODE assertion should be skipped.
    result = execute_pex(disable_assertions=True)
    result.assert_success()
    assert colors.green("Worked: program args") in result.output
