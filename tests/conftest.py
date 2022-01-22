# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex import testing
from pex.interpreter import PythonInterpreter
from pex.platforms import Platform
from pex.testing import PY27, PY37, PY310, ensure_python_interpreter


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
def py37():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY37))


@pytest.fixture
def py310():
    # type: () -> PythonInterpreter
    return PythonInterpreter.from_binary(ensure_python_interpreter(PY310))
