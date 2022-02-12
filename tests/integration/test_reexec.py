# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import subprocess
import sys
from textwrap import dedent

import pytest

from pex.common import temporary_dir
from pex.interpreter import PythonInterpreter
from pex.testing import (
    PY27,
    PY310,
    ensure_python_interpreter,
    make_env,
    run_pex_command,
    run_simple_pex,
)
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, List, Optional


def _assert_exec_chain(
    exec_chain=None,  # type: Optional[List[str]]
    pex_python=None,  # type: Optional[str]
    pex_python_path=None,  # type: Optional[Iterable[str]]
    interpreter_constraints=None,  # type: Optional[Iterable[str]]
    pythonpath=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> None
    with temporary_dir() as td:
        test_pex = os.path.join(td, "test.pex")

        args = ["-o", test_pex]
        if interpreter_constraints:
            args.extend("--interpreter-constraint={}".format(ic) for ic in interpreter_constraints)

        env = os.environ.copy()
        PATH = env["PATH"].split(os.pathsep)

        def add_to_path(entry):
            # type: (str) -> None
            if os.path.isfile(entry):
                entry = os.path.dirname(entry)
            PATH.append(entry)

        if pex_python:
            add_to_path(pex_python)
        if pex_python_path:
            for path in pex_python_path:
                add_to_path(path)

        env["PATH"] = os.pathsep.join(PATH)
        result = run_pex_command(args, env=env)
        result.assert_success()

        env = make_env(
            _PEX_EXEC_CHAIN=1,
            PEX_INTERPRETER=1,
            PEX_PYTHON=pex_python,
            PEX_PYTHON_PATH=os.pathsep.join(pex_python_path) if pex_python_path else None,
            PYTHONPATH=os.pathsep.join(pythonpath) if pythonpath else None,
        )

        initial_interpreter = PythonInterpreter.get()
        output = subprocess.check_output(
            [
                initial_interpreter.binary,
                test_pex,
                "-c",
                "import json, os; print(json.dumps(os.environ.copy()))",
            ],
            env=env,
        )
        final_env = json.loads(output.decode("utf-8"))

        assert "PEX_PYTHON" not in final_env
        assert "PEX_PYTHON_PATH" not in final_env
        assert "_PEX_SHOULD_EXIT_BOOTSTRAP_REEXEC" not in final_env

        expected_exec_interpreters = [initial_interpreter]
        if exec_chain:
            expected_exec_interpreters.extend(PythonInterpreter.from_binary(b) for b in exec_chain)
        final_interpreter = expected_exec_interpreters[-1]
        if final_interpreter.is_venv:
            # If the last interpreter in the chain is in a virtual environment, it should be fully
            # resolved and re-exec'd against in order to escape the virtual environment since we're
            # not setting PEX_INHERIT_PATH in these tests.
            resolved = final_interpreter.resolve_base_interpreter()
            if exec_chain:
                # There is already an expected reason to re-exec; so no extra exec step is needed.
                expected_exec_interpreters[-1] = resolved
            else:
                # The expected exec chain is just the initial_interpreter, but it turned out to be a
                # venv which forces a re-exec.
                expected_exec_interpreters.append(resolved)
        expected_exec_chain = [i.binary for i in expected_exec_interpreters]
        actual_exec_chain = final_env["_PEX_EXEC_CHAIN"].split(os.pathsep)
        assert expected_exec_chain == actual_exec_chain


def test_pex_no_reexec_no_constraints():
    # type: () -> None
    _assert_exec_chain()


def test_pex_reexec_no_constraints_pythonpath_present():
    # type: () -> None
    _assert_exec_chain(exec_chain=[sys.executable], pythonpath=["."])


def test_pex_no_reexec_constraints_match_current():
    # type: () -> None
    _assert_exec_chain(interpreter_constraints=[PythonInterpreter.get().identity.requirement])


def test_pex_reexec_constraints_match_current_pythonpath_present():
    # type: () -> None
    _assert_exec_chain(
        exec_chain=[sys.executable],
        pythonpath=["."],
        interpreter_constraints=[PythonInterpreter.get().identity.requirement],
    )


def test_pex_reexec_constraints_dont_match_current_pex_python_path():
    # type: () -> None
    py310_interpreter = ensure_python_interpreter(PY310)
    py27_interpreter = ensure_python_interpreter(PY27)
    _assert_exec_chain(
        exec_chain=[py310_interpreter],
        pex_python_path=[py27_interpreter, py310_interpreter],
        interpreter_constraints=["=={}".format(PY310)],
    )


def test_pex_reexec_constraints_dont_match_current_pex_python_path_min_py_version_selected():
    # type: () -> None
    py310_interpreter = ensure_python_interpreter(PY310)
    py27_interpreter = ensure_python_interpreter(PY27)
    _assert_exec_chain(
        exec_chain=[py27_interpreter], pex_python_path=[py310_interpreter, py27_interpreter]
    )


def test_pex_reexec_constraints_dont_match_current_pex_python():
    # type: () -> None
    version = PY27 if sys.version_info[:2] == (3, 8) else PY310
    interpreter = ensure_python_interpreter(version)
    _assert_exec_chain(
        exec_chain=[interpreter],
        pex_python=interpreter,
        interpreter_constraints=["=={}".format(version)],
    )


@pytest.mark.xfail(reason="See https://github.com/pantsbuild/pants/issues/4682")
def test_pex_re_exec_failure():
    # type: () -> None
    with temporary_dir() as output_dir:

        # create 2 pex files for PEX_PATH
        pex1_path = os.path.join(output_dir, "pex1.pex")
        res1 = run_pex_command(["--disable-cache", "requests", "-o", pex1_path])
        res1.assert_success()
        pex2_path = os.path.join(output_dir, "pex2.pex")
        res2 = run_pex_command(["--disable-cache", "flask", "-o", pex2_path])
        res2.assert_success()
        pex_path = ":".join(os.path.join(output_dir, name) for name in ("pex1.pex", "pex2.pex"))

        # create test file test.py that attmepts to import modules from pex1/pex2
        test_file_path = os.path.join(output_dir, "test.py")
        with open(test_file_path, "w") as fh:
            fh.write(
                dedent(
                    """
                    import requests
                    import flask
                    import sys
                    import os
                    import subprocess
                    if 'RAN_ONCE' in os.environ::
                        print('Hello world')
                    else:
                        env = os.environ.copy()
                        env['RAN_ONCE'] = '1'
                        subprocess.call([sys.executable] + sys.argv, env=env)
                        sys.exit()
                    """
                )
            )

        # set up env for pex build with PEX_PATH in the environment
        env = make_env(PEX_PATH=pex_path)

        # build composite pex of pex1/pex1
        pex_out_path = os.path.join(output_dir, "out.pex")
        run_pex_command(["--disable-cache", "wheel", "-o", pex_out_path])

        # run test.py with composite env
        stdout, rc = run_simple_pex(pex_out_path, [test_file_path], env=env)

        assert rc == 0
        assert stdout == b"Hello world\n"
