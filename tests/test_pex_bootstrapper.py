# Copyright 2015 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import sys
from textwrap import dedent

import pytest

from pex.common import temporary_dir
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import (
    InterpreterConstraints,
    UnsatisfiableInterpreterConstraintsError,
)
from pex.pex import PEX
from pex.pex_bootstrapper import (
    InterpreterTest,
    ensure_venv,
    find_compatible_interpreter,
    iter_compatible_interpreters,
)
from pex.pex_builder import PEXBuilder
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from testing import PY39, PY310, PY311, ensure_python_interpreter, subprocess

if TYPE_CHECKING:
    from typing import Any, Iterable, List, Optional


def basenames(*paths):
    # type: (*str) -> Iterable[str]
    return [os.path.basename(p) for p in paths]


def find_interpreters(
    path,  # type: Iterable[str]
    valid_basenames=None,  # type: Optional[Iterable[str]]
    constraints=(),  # type: Iterable[str]
    preferred_interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> List[str]
    return [
        interp.binary
        for interp in iter_compatible_interpreters(
            path=tuple(path),
            valid_basenames=valid_basenames,
            interpreter_constraints=InterpreterConstraints.parse(*constraints),
            preferred_interpreter=preferred_interpreter,
        )
    ]


def test_find_compatible_interpreters():
    # type: () -> None
    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)
    py311 = ensure_python_interpreter(PY311)
    path = [py39, py310, py311]

    assert [py310, py311] == find_interpreters(path, constraints=[">3.10"])
    assert [py39] == find_interpreters(path, constraints=["<3.10"])

    assert [py311] == find_interpreters(path, constraints=[">{}".format(PY310)])
    assert [py310] == find_interpreters(path, constraints=[">{}, <{}".format(PY39, PY311)])
    assert [py311] == find_interpreters(path, constraints=[">=3.11"])

    with pytest.raises(UnsatisfiableInterpreterConstraintsError):
        find_interpreters(path, constraints=["<3"])

    with pytest.raises(UnsatisfiableInterpreterConstraintsError):
        find_interpreters(path, constraints=[">4"])

    with pytest.raises(UnsatisfiableInterpreterConstraintsError):
        find_interpreters(path, constraints=[">{}, <{}".format(PY39, PY310)])

    # All interpreters on PATH including whatever interpreter is currently running.
    all_known_interpreters = set(PythonInterpreter.from_binary(python) for python in path)
    all_known_interpreters.add(PythonInterpreter.get())

    interpreters = set(
        iter_compatible_interpreters(
            path, interpreter_constraints=InterpreterConstraints.parse("<3.10")
        )
    )
    i_rendered = "\n      ".join(sorted(map(repr, interpreters)))
    aki_rendered = "\n      ".join(sorted(map(repr, all_known_interpreters)))
    assert interpreters.issubset(all_known_interpreters), dedent(
        """
        interpreters '<3':
          {interpreters}
        
        all known interpreters:
          {all_known_interpreters}
        """.format(
            interpreters=i_rendered, all_known_interpreters=aki_rendered
        )
    )


def test_find_compatible_interpreters_none():
    # type: () -> None
    assert [] == find_interpreters([os.path.devnull])


def test_find_compatible_interpreters_none_with_valid_basenames():
    # type: () -> None
    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)
    path = [py39, py310]

    with pytest.raises(UnsatisfiableInterpreterConstraintsError) as exec_info:
        find_interpreters(path, valid_basenames=["python3.6"])

    exception_message = str(exec_info.value)
    assert py39 not in exception_message
    assert py310 not in exception_message


def test_find_compatible_interpreters_none_with_constraints():
    # type: () -> None
    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)
    path = [py39, py310]

    with pytest.raises(UnsatisfiableInterpreterConstraintsError) as exec_info:
        find_interpreters(path, constraints=[">=3.11"])

    exception_message = str(exec_info.value)
    assert py39 in exception_message
    assert py310 in exception_message
    assert ">=3.11" in exception_message


def test_find_compatible_interpreters_none_with_valid_basenames_and_constraints():
    # type: () -> None
    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)
    path = [py310, py39]

    with pytest.raises(UnsatisfiableInterpreterConstraintsError) as exec_info:
        find_interpreters(path, valid_basenames=basenames(py39), constraints=[">=3.10"])

    exception_message = str(exec_info.value)
    assert py39 in exception_message
    assert os.path.basename(py39) in exception_message
    assert py310 not in exception_message
    assert ">=3.10" in exception_message


def test_find_compatible_interpreters_with_valid_basenames():
    # type: () -> None
    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)
    py311 = ensure_python_interpreter(PY311)
    path = [py39, py310, py311]

    assert [py39] == find_interpreters(path, valid_basenames=basenames(py39))
    assert [py310, py311] == find_interpreters(
        path, valid_basenames=basenames(*reversed([py310, py311]))
    )


def test_find_compatible_interpreters_with_valid_basenames_and_constraints():
    # type: () -> None
    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)
    py311 = ensure_python_interpreter(PY311)
    path = [py39, py310, py311]

    assert [py310] == find_interpreters(
        path, valid_basenames=basenames(py39, py310), constraints=[">=3.10"]
    )


def test_find_compatible_interpreters_bias_current():
    # type: () -> None
    py310 = ensure_python_interpreter(PY310)
    current_interpreter = PythonInterpreter.get()
    assert [current_interpreter.binary, py310] == find_interpreters([py310, sys.executable])
    assert [current_interpreter.binary, py310] == find_interpreters([sys.executable, py310])


def test_find_compatible_interpreters_siblings_of_current_issues_1109():
    # type: () -> None
    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)

    with temporary_dir() as path_entry:
        python39 = os.path.join(path_entry, "python3.9")
        shutil.copy(py39, python39)

        python310 = os.path.join(path_entry, "python3.10")
        shutil.copy(py310, python310)

        assert [os.path.realpath(p) for p in (python310, python39)] == find_interpreters(
            path=[path_entry], preferred_interpreter=PythonInterpreter.from_binary(python310)
        )


def test_ensure_venv_activate_issues_1276(tmpdir):
    # type: (Any) -> None
    pex_root = os.path.join(str(tmpdir), "pex_root")
    pb = PEXBuilder()
    pb.info.pex_root = pex_root
    pb.info.venv = True
    pb.freeze()

    venv_pex = ensure_venv(PEX(pb.path()))

    expected_python_bin_dir = (
        subprocess.check_output(
            args=[
                venv_pex.pex,
                "-c",
                "import os, sys; print(os.path.realpath(os.path.dirname(sys.executable)))",
            ],
        )
        .decode("utf-8")
        .strip()
    )
    bash_activate = venv_pex.bin_file("activate")

    subprocess.check_call(
        args=[
            "/usr/bin/env",
            "bash",
            "-c",
            dedent(
                """\
                source "{activate_script}"

                actual_python_bin_dir="$(dirname "$(command -v python)")"
                expected_python_bin_dir="{expected_python_bin_dir}"

                if [ "${{actual_python_bin_dir}}" != "${{expected_python_bin_dir}}" ]; then
                    echo >&2 "Actual Python Bin Dir: ${{actual_python_bin_dir}}"
                    echo >&2 "Expected Python Bin Dir: ${{expected_python_bin_dir}}"
                  exit 42
                fi
                """.format(
                    activate_script=bash_activate, expected_python_bin_dir=expected_python_bin_dir
                )
            ),
        ]
    )


def test_pp_invalid():
    # type: () -> None
    with ENV.patch(PEX_PYTHON="/invalid/abs/python"):
        with pytest.raises(
            UnsatisfiableInterpreterConstraintsError,
            match=(
                r"The specified PEX_PYTHON=/invalid/abs/python could not be identified as a "
                r"valid Python interpreter."
            ),
        ):
            find_compatible_interpreter()


def test_pp_exact():
    # type: () -> None
    py310 = ensure_python_interpreter(PY310)
    with ENV.patch(PEX_PYTHON=py310):
        assert PythonInterpreter.from_binary(py310) == find_compatible_interpreter()


def test_pp_exact_on_ppp():
    # type: () -> None

    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)
    py311 = ensure_python_interpreter(PY311)

    with ENV.patch(
        PEX_PYTHON=py311,
        PEX_PYTHON_PATH=os.pathsep.join(os.path.dirname(py) for py in (py39, py310, py311)),
    ):
        assert PythonInterpreter.from_binary(py311) == find_compatible_interpreter()


def test_pp_exact_satisfies_constraints():
    # type: () -> None

    py310 = ensure_python_interpreter(PY310)

    pb = PEXBuilder()
    pb.info.interpreter_constraints = InterpreterConstraints.parse(">=3.7")
    pb.freeze()

    with ENV.patch(PEX_PYTHON=py310):
        assert PythonInterpreter.from_binary(py310) == find_compatible_interpreter(
            interpreter_test=InterpreterTest(entry_point=pb.path(), pex_info=pb.info),
        )


def test_pp_exact_does_not_satisfy_constraints():
    # type: () -> None

    py310 = ensure_python_interpreter(PY310)

    pb = PEXBuilder()
    pb.info.interpreter_constraints = InterpreterConstraints.parse("<=3.7")
    pb.freeze()

    with ENV.patch(PEX_PYTHON=py310):
        with pytest.raises(
            UnsatisfiableInterpreterConstraintsError,
            match=r"Failed to find a compatible PEX_PYTHON={pp}.".format(pp=py310),
        ):
            find_compatible_interpreter(
                interpreter_test=InterpreterTest(entry_point=pb.path(), pex_info=pb.info),
            )


def test_pp_exact_not_on_ppp():
    # type: () -> None

    py39 = ensure_python_interpreter(PY39)
    py310 = ensure_python_interpreter(PY310)
    py311 = ensure_python_interpreter(PY311)

    with ENV.patch(
        PEX_PYTHON=py311,
        PEX_PYTHON_PATH=os.pathsep.join(os.path.dirname(py) for py in (py39, py310)),
    ):
        with pytest.raises(
            UnsatisfiableInterpreterConstraintsError,
            match=r"The specified PEX_PYTHON={pp} did not meet other constraints.".format(pp=py311),
        ):
            find_compatible_interpreter()
