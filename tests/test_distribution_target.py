# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import pytest

from pex.distribution_target import DistributionTarget
from pex.interpreter import PythonInterpreter


@pytest.fixture
def current_interpreter():
    # type: () -> PythonInterpreter
    return PythonInterpreter.get()


def test_interpreter_platform_mutex(current_interpreter):
    # type: (PythonInterpreter) -> None

    def assert_is_platform(target):
        # type: (DistributionTarget) -> None
        assert target.is_platform
        assert not target.is_interpreter

    def assert_is_interpreter(target):
        # type: (DistributionTarget) -> None
        assert target.is_interpreter
        assert not target.is_platform

    assert_is_interpreter(DistributionTarget.current())
    assert_is_interpreter(DistributionTarget())
    assert_is_interpreter(DistributionTarget.for_interpreter(current_interpreter))
    assert_is_platform(DistributionTarget.for_platform(current_interpreter.platform))

    with pytest.raises(DistributionTarget.AmbiguousTargetError):
        DistributionTarget(interpreter=current_interpreter, platform=current_interpreter.platform)


def test_manylinux(current_interpreter):
    # type: (PythonInterpreter) -> None

    current_platform = current_interpreter.platform

    target = DistributionTarget.for_platform(current_platform, manylinux="foo")
    assert (current_platform, "foo") == target.get_platform()

    target = DistributionTarget(platform=current_platform, manylinux="bar")
    assert (current_platform, "bar") == target.get_platform()

    with pytest.raises(DistributionTarget.ManylinuxOutOfContextError):
        DistributionTarget(manylinux="baz")

    with pytest.raises(DistributionTarget.ManylinuxOutOfContextError):
        DistributionTarget(interpreter=PythonInterpreter.get(), manylinux="baz")

    target = DistributionTarget.for_interpreter(current_interpreter)
    assert (current_platform, None) == target.get_platform()
