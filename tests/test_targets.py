# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex import targets
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.platforms import Platform
from pex.targets import AbbreviatedPlatform, CompletePlatform, LocalInterpreter, Targets


@pytest.fixture
def current_interpreter():
    # type: () -> PythonInterpreter
    return PythonInterpreter.get()


def test_current(current_interpreter):
    # type: (PythonInterpreter) -> None
    assert LocalInterpreter.create() == targets.current()
    assert LocalInterpreter.create(current_interpreter) == targets.current()


def test_interpreter(
    py27,  # type: PythonInterpreter
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None
    assert Targets().interpreter is None
    assert py27 == Targets(interpreters=(py27,)).interpreter
    assert py27 == Targets(interpreters=(py27, current_interpreter)).interpreter


def test_unique_targets(
    py27,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    current_interpreter,  # type: PythonInterpreter
    current_platform,  # type: Platform
):
    # type: (...) -> None
    assert (
        OrderedSet([targets.current()]) == Targets().unique_targets()
    ), "Expected the default TargetConfiguration to produce the current interpreter."

    assert OrderedSet([targets.current()]) == Targets(platforms=(None,)).unique_targets(), (
        "Expected the 'current' platform - which maps to `None` - to produce the current "
        "interpreter when no interpreters were configured."
    )

    assert (
        OrderedSet([LocalInterpreter.create(py27)])
        == Targets(interpreters=(py27,), platforms=(None,)).unique_targets()
    ), (
        "Expected the 'current' platform - which maps to `None` - to be ignored when at least one "
        "concrete interpreter for the current platform is configured."
    )

    assert (
        OrderedSet([AbbreviatedPlatform.create(current_platform)])
        == Targets(platforms=(current_platform,)).unique_targets()
    )

    assert (
        OrderedSet(LocalInterpreter.create(i) for i in (py27, py37, py310))
        == Targets(interpreters=(py27, py37, py310)).unique_targets()
    )

    complete_platform_current = CompletePlatform.from_interpreter(current_interpreter)
    complete_platform_py27 = CompletePlatform.from_interpreter(py27)
    assert (
        OrderedSet([complete_platform_current, complete_platform_py27])
        == Targets(
            complete_platforms=(complete_platform_current, complete_platform_py27)
        ).unique_targets()
    )
