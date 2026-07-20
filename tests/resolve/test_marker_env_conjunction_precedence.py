# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

from pex.interpreter_implementation import InterpreterImplementation
from pex.resolve.target_system import MarkerEnv, TargetSystem, UniversalTarget
from pex.third_party.packaging.markers import Marker


def test_issue_3206():
    # type: () -> None

    marker_env = MarkerEnv.create(
        extras=(),
        universal_target=UniversalTarget(
            implementation=InterpreterImplementation.PYPY, systems=(TargetSystem.LINUX,)
        ),
    )

    # N.B.: This works both on a simple LR scan and with proper precedence logic.
    assert marker_env.evaluate(
        Marker("sys_platform == 'win32' and sys_platform == 'aix' or sys_platform == 'linux'")
    )

    # No precedence left implicit.
    assert marker_env.evaluate(
        Marker("sys_platform == 'linux' or (sys_platform == 'win32' and sys_platform == 'aix')")
    )

    # Implicit precedence to respect:
    assert marker_env.evaluate(
        Marker("sys_platform == 'linux' or sys_platform == 'win32' and sys_platform == 'aix'")
    ), (
        "The `and` operator should bind more tightly than the `or` operator per the PEP-508 "
        "grammar: "
        "https://packaging.python.org/en/latest/specifications/dependency-specifiers/#complete-grammar"
    )

    assert marker_env.evaluate(
        Marker(
            "sys_platform == 'darwin' "
            "or sys_platform == 'win32' and sys_platform == 'aix' "
            "or sys_platform == 'linux'"
        )
    )

    assert marker_env.evaluate(
        Marker(
            "sys_platform == 'darwin' "
            "or sys_platform == 'linux' and platform_python_implementation == 'PyPy'"
        )
    )
    assert not marker_env.evaluate(
        Marker(
            "sys_platform == 'darwin' "
            "or sys_platform == 'linux' and platform_python_implementation == 'CPython'"
        )
    )
    assert marker_env.evaluate(
        Marker(
            "sys_platform == 'darwin' "
            "or sys_platform == 'linux' and platform_python_implementation == 'CPython'"
            "or sys_platform != 'aix' and platform_python_implementation == 'PyPy'"
        )
    )
