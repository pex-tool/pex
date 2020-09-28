# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from textwrap import dedent

import pytest

from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import UnsatisfiableInterpreterConstraintsError
from pex.pex_bootstrapper import iter_compatible_interpreters
from pex.testing import PY27, PY35, PY36, ensure_python_interpreter
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import AnyStr, Iterable, List, Optional


def basenames(*paths):
    # type: (*str) -> Iterable[str]
    return [os.path.basename(p) for p in paths]


def find_interpreters(path, valid_basenames=None, constraints=None):
    # type: (Iterable[str], Optional[Iterable[str]], Optional[Iterable[str]]) -> List[AnyStr]
    return [
        interp.binary
        for interp in iter_compatible_interpreters(
            path=os.pathsep.join(path),
            valid_basenames=valid_basenames,
            interpreter_constraints=constraints,
        )
    ]


def test_find_compatible_interpreters():
    # type: () -> None
    py27 = ensure_python_interpreter(PY27)
    py35 = ensure_python_interpreter(PY35)
    py36 = ensure_python_interpreter(PY36)
    path = [py27, py35, py36]

    assert [py35, py36] == find_interpreters(path, constraints=[">3"])
    assert [py27] == find_interpreters(path, constraints=["<3"])

    assert [py36] == find_interpreters(path, constraints=[">{}".format(PY35)])
    assert [py35] == find_interpreters(path, constraints=[">{}, <{}".format(PY27, PY36)])
    assert [py36] == find_interpreters(path, constraints=[">=3.6"])

    with pytest.raises(UnsatisfiableInterpreterConstraintsError):
        find_interpreters(path, constraints=["<2"])

    with pytest.raises(UnsatisfiableInterpreterConstraintsError):
        find_interpreters(path, constraints=[">4"])

    with pytest.raises(UnsatisfiableInterpreterConstraintsError):
        find_interpreters(path, constraints=[">{}, <{}".format(PY27, PY35)])

    # All interpreters on PATH including whatever interpreter is currently running.
    all_known_interpreters = set(PythonInterpreter.all())
    all_known_interpreters.add(PythonInterpreter.get())

    interpreters = set(iter_compatible_interpreters(interpreter_constraints=["<3"]))
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
    py27 = ensure_python_interpreter(PY27)
    py35 = ensure_python_interpreter(PY35)
    path = [py27, py35]

    with pytest.raises(UnsatisfiableInterpreterConstraintsError) as exec_info:
        find_interpreters(path, valid_basenames=["python3.6"])

    exception_message = str(exec_info.value)
    assert py27 not in exception_message
    assert py35 not in exception_message


def test_find_compatible_interpreters_none_with_constraints():
    # type: () -> None
    py27 = ensure_python_interpreter(PY27)
    py35 = ensure_python_interpreter(PY35)
    path = [py27, py35]

    with pytest.raises(UnsatisfiableInterpreterConstraintsError) as exec_info:
        find_interpreters(path, constraints=[">=3.6"])

    exception_message = str(exec_info.value)
    assert py27 in exception_message
    assert py35 in exception_message
    assert ">=3.6" in exception_message


def test_find_compatible_interpreters_none_with_valid_basenames_and_constraints():
    # type: () -> None
    py27 = ensure_python_interpreter(PY27)
    py35 = ensure_python_interpreter(PY35)
    path = [py27, py35]

    with pytest.raises(UnsatisfiableInterpreterConstraintsError) as exec_info:
        find_interpreters(path, valid_basenames=basenames(py27), constraints=[">=3.6"])

    exception_message = str(exec_info.value)
    assert py27 in exception_message
    assert py35 not in exception_message
    assert os.path.basename(py27) in exception_message, exception_message
    assert ">=3.6" in exception_message


def test_find_compatible_interpreters_with_valid_basenames():
    # type: () -> None
    py27 = ensure_python_interpreter(PY27)
    py35 = ensure_python_interpreter(PY35)
    py36 = ensure_python_interpreter(PY36)
    path = [py27, py35, py36]

    assert [py35] == find_interpreters(path, valid_basenames=basenames(py35))
    assert [py27, py36] == find_interpreters(
        path, valid_basenames=basenames(*reversed([py27, py36]))
    )


def test_find_compatible_interpreters_with_valid_basenames_and_constraints():
    # type: () -> None
    py27 = ensure_python_interpreter(PY27)
    py35 = ensure_python_interpreter(PY35)
    py36 = ensure_python_interpreter(PY36)
    path = [py27, py35, py36]

    assert [py35] == find_interpreters(
        path, valid_basenames=basenames(py27, py35), constraints=[">=3"]
    )


def test_find_compatible_interpreters_bias_current():
    # type: () -> None
    py36 = ensure_python_interpreter(PY36)
    assert [os.path.realpath(sys.executable), py36] == find_interpreters([py36, sys.executable])
    assert [os.path.realpath(sys.executable), py36] == find_interpreters([sys.executable, py36])
