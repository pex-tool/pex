# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.distribution_target import DistributionTarget
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.platforms import Platform
from pex.resolve.target_configuration import TargetConfiguration


def test_interpreter(
    py27,  # type: PythonInterpreter
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None
    assert TargetConfiguration().interpreter is None
    assert py27 == TargetConfiguration(interpreters=[py27]).interpreter
    assert py27 == TargetConfiguration(interpreters=[py27, current_interpreter]).interpreter


def test_unique_targets(
    py27,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    current_interpreter,  # type: PythonInterpreter
    current_platform,  # type: Platform
):
    # type: (...) -> None
    assert (
        OrderedSet([DistributionTarget.current()]) == TargetConfiguration().unique_targets()
    ), "Expected the default TargetConfiguration to produce the current interpreter."

    assert (
        OrderedSet([DistributionTarget.current()])
        == TargetConfiguration(platforms=[None]).unique_targets()
    ), (
        "Expected the 'current' platform - which maps to `None` - to produce the current "
        "interpreter when no interpreters were configured."
    )

    assert (
        OrderedSet([DistributionTarget.for_interpreter(py27)])
        == TargetConfiguration(interpreters=[py27], platforms=[None]).unique_targets()
    ), (
        "Expected the 'current' platform - which maps to `None` - to be ignored when at least one "
        "concrete interpreter for the current platform is configured."
    )

    assert (
        OrderedSet([DistributionTarget.for_platform(current_platform)])
        == TargetConfiguration(platforms=[current_platform]).unique_targets()
    )

    assert (
        OrderedSet(DistributionTarget.for_interpreter(i) for i in (py27, py37, py310))
        == TargetConfiguration(interpreters=[py27, py37, py310]).unique_targets()
    )
