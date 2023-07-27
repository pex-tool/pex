# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

import testing
from pex.interpreter import PythonInterpreter
from pex.platforms import Platform
from testing import PY27, PY38, PY39, PY310, ensure_python_interpreter


@pytest.fixture(scope="session")
def pex_project_dir():
    # type: () -> str
    return testing.pex_project_dir()


@pytest.fixture
def current_interpreter():
    # type: () -> PythonInterpreter
    return PythonInterpreter.get()


@pytest.fixture
def current_platform(current_interpreter):
    # type: (PythonInterpreter) -> Platform
    return current_interpreter.platform


@pytest.fixture
def py27():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY27))


@pytest.fixture
def py38():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY38))


@pytest.fixture
def py39():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY39))


@pytest.fixture
def py310():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY310))
