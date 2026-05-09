# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

import pytest

from pex.common import safe_mkdtemp
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import InterpreterConstraint
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, List

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class InterpreterTool(object):
    tools_pex = attr.ib()  # type: str
    interpreter = attr.ib()  # type: PythonInterpreter
    other_interpreters = attr.ib(default=())  # type: Iterable[PythonInterpreter]

    @classmethod
    def create(
        cls,
        tools_pex,  # type: str
        interpreter,  # type: PythonInterpreter
        *other_interpreters  # type: PythonInterpreter
    ):
        # type: (...) -> InterpreterTool
        return cls(
            tools_pex=tools_pex,
            interpreter=interpreter,
            other_interpreters=other_interpreters,
        )

    def run(
        self,
        *args,  # type: str
        **env  # type: str
    ):
        # type: (...) -> str
        cmd = [self.tools_pex, "interpreter"]
        if args:
            cmd.extend(args)

        environ = os.environ.copy()
        interpreters = [self.interpreter]
        interpreters.extend(self.other_interpreters)
        environ.update(
            PEX_PYTHON_PATH=os.pathsep.join(interpreter.binary for interpreter in interpreters),
            PEX_TOOLS="1",
        )
        environ.update(env)

        _, stdout, _ = self.interpreter.execute(args=cmd, env=environ)
        return stdout


@pytest.fixture(
    params=[pytest.param(["--include-tools"], id="PEX"), pytest.param(["--rc"], id="PEX.rc")]
)
def interpreter_tool(
    request,  # type: Any
    tmpdir,  # type: Any
    py39,  # type: PythonInterpreter
    py311,  # type: PythonInterpreter
):
    # type: (...) -> InterpreterTool
    tools_pex = os.path.join(str(tmpdir), "tools.pex")
    run_pex_command(args=["-o", tools_pex] + request.param, python=py39.binary).assert_success()
    return InterpreterTool.create(tools_pex, py39, py311)


def expected_basic(interpreter):
    # type: (PythonInterpreter) -> str
    return interpreter.binary


def test_basic(
    py39,  # type: PythonInterpreter
    interpreter_tool,  # type: InterpreterTool
):
    # type: (...) -> None
    output = interpreter_tool.run()
    assert expected_basic(py39) == output.strip()


def test_basic_all(
    py39,  # type: PythonInterpreter
    py311,  # type: PythonInterpreter
    interpreter_tool,  # type: InterpreterTool
):
    # type: (...) -> None
    output = interpreter_tool.run("-a")
    assert [expected_basic(interpreter) for interpreter in (py39, py311)] == output.splitlines()


def expected_verbose(interpreter):
    # type: (PythonInterpreter) -> Dict[str, Any]
    return {
        "path": interpreter.binary,
        "platform": str(interpreter.platform),
        "requirement": str(InterpreterConstraint.exact_version(interpreter)),
    }


def test_verbose(
    py39,  # type: PythonInterpreter
    interpreter_tool,  # type: InterpreterTool
):
    # type: (...) -> None
    output = interpreter_tool.run("-v")
    assert expected_verbose(py39) == json.loads(output)


def test_verbose_all(
    py39,  # type: PythonInterpreter
    py311,  # type: PythonInterpreter
    interpreter_tool,  # type: InterpreterTool
):
    # type: (...) -> None
    output = interpreter_tool.run("-va")
    assert [expected_verbose(interpreter) for interpreter in (py39, py311)] == [
        json.loads(line) for line in output.splitlines()
    ]


def expected_verbose_verbose(interpreter):
    # type: (PythonInterpreter) -> Dict[str, Any]
    expected = expected_verbose(interpreter)
    expected.update(supported_tags=interpreter.identity.supported_tags.to_string_list())
    return expected


def test_verbose_verbose(
    py39,  # type: PythonInterpreter
    interpreter_tool,  # type: InterpreterTool
):
    # type: (...) -> None
    output = interpreter_tool.run("-vv")
    assert expected_verbose_verbose(py39) == json.loads(output)


def test_verbose_verbose_verbose(
    py39,  # type: PythonInterpreter
    interpreter_tool,  # type: InterpreterTool
):
    # type: (...) -> None
    output = interpreter_tool.run("-vvv")
    expected = expected_verbose_verbose(py39)
    expected.update(env_markers=py39.identity.env_markers.as_dict(), venv=False)
    assert expected == json.loads(output)


@pytest.mark.parametrize(
    "tools_pex_args",
    [
        pytest.param(["--include-tools"], id="PEX"),
        pytest.param(["--rc"], id="PEX.rc"),
    ],
)
def test_verbose_verbose_verbose_venv(
    py310,  # type: PythonInterpreter
    tools_pex_args,  # type: List[str]
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None
    venv = Virtualenv.create(venv_dir=safe_mkdtemp(), interpreter=py310, force=True)
    assert venv.interpreter.is_venv

    tools_pex = tmpdir.join("tools.pex")
    run_pex_command(args=["-o", tools_pex] + tools_pex_args).assert_success()

    # N.B.: Non-venv-mode PEXes always escape venvs to prevent `sys.path` contamination unless
    # `PEX_INHERIT_PATH` is not "false".
    output = InterpreterTool.create(tools_pex, venv.interpreter).run(
        "-vvv", PEX_INHERIT_PATH="fallback"
    )

    expected = expected_verbose_verbose(venv.interpreter)
    expected.update(
        env_markers=venv.interpreter.identity.env_markers.as_dict(),
        venv=True,
        base_interpreter=py310.binary,
    )
    assert expected == json.loads(output)
