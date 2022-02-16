# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.platforms import Platform
from pex.targets import AbbreviatedPlatform, LocalInterpreter, Target, Targets


@pytest.fixture
def current_interpreter():
    # type: () -> PythonInterpreter
    return PythonInterpreter.get()


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
        OrderedSet([Target.current()]) == Targets().unique_targets()
    ), "Expected the default TargetConfiguration to produce the current interpreter."

    assert OrderedSet([Target.current()]) == Targets(platforms=(None,)).unique_targets(), (
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
