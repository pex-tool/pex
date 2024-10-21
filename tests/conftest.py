# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import getpass
import os.path
import tempfile

import pytest
from _pytest.config import hookimpl  # type: ignore[import]

import testing
from pex.interpreter import PythonInterpreter
from pex.platforms import Platform
from pex.typing import TYPE_CHECKING
from testing import PY27, PY38, PY39, PY310, ensure_python_interpreter
from testing.pytest import tmp, track_status_hook

if TYPE_CHECKING:
    from typing import Iterator

    from _pytest.fixtures import FixtureRequest  # type: ignore[import]
    from _pytest.nodes import Item  # type: ignore[import]
    from _pytest.reports import TestReport  # type: ignore[import]


@pytest.fixture(scope="session")
def pex_project_dir():
    # type: () -> str
    return testing.pex_project_dir()


@pytest.fixture(scope="session")
def tmpdir_factory(request):
    # type: (FixtureRequest) -> tmp.TempdirFactory

    # We use existing pytest configuration sources and values for tmpdir here to be drop-in
    # ~compatible.

    basetemp = request.config.option.basetemp or os.path.join(
        tempfile.gettempdir(), "pytest-of-{user}".format(user=getpass.getuser() or "unknown")
    )

    retention_count = int(request.config.getini("tmp_path_retention_count"))
    if retention_count < 0:
        raise ValueError(
            "The `tmp_path_retention_count` value must be >= 0. Given: {count}.".format(
                count=retention_count
            )
        )

    retention_policy = tmp.RetentionPolicy.for_value(
        request.config.getini("tmp_path_retention_policy")
    )

    return tmp.tmpdir_factory(
        basetemp=basetemp, retention_count=retention_count, retention_policy=retention_policy
    )


# This exposes the proper hooks for Python 2 or Python 3 as the case may be - the names on the LHS
# are key.
pytest_addoption = track_status_hook.pytest_addoption
pytest_runtest_makereport = track_status_hook.hook


@pytest.fixture
def tmpdir(
    tmpdir_factory,  # type: tmp.TempdirFactory
    request,  # type: FixtureRequest
):
    # type: (...) -> Iterator[tmp.Tempdir]
    temp_directory = tmpdir_factory.mktemp(name=request.node.name)
    try:
        yield temp_directory
    finally:
        if (
            tmpdir_factory.retention_policy is tmp.RetentionPolicy.FAILED
            and track_status_hook.passed(request.node)
        ) or tmpdir_factory.retention_policy is tmp.RetentionPolicy.NONE:
            temp_directory.safe_remove()


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
