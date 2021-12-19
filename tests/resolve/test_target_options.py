# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os
from argparse import ArgumentParser, ArgumentTypeError

import pytest

from pex.interpreter import PythonInterpreter
from pex.platforms import Platform
from pex.resolve import target_options
from pex.resolve.target_configuration import TargetConfiguration
from pex.testing import IS_MAC, environment_as
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Iterable, List, Optional, Tuple


def compute_target_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> TargetConfiguration
    options = parser.parse_args(args=args)
    return target_options.configure(options)


def test_clp_manylinux(parser):
    # type: (ArgumentParser) -> None
    target_options.register(parser)

    target_configuration = compute_target_configuration(parser, args=[])
    assert (
        target_configuration.assume_manylinux
    ), "The --manylinux option should default to some value."

    def assert_manylinux(value):
        # type: (str) -> None
        rc = compute_target_configuration(parser, args=["--manylinux", value])
        assert value == rc.assume_manylinux

    # Legacy manylinux standards should be supported.
    assert_manylinux("manylinux1_x86_64")
    assert_manylinux("manylinux2010_x86_64")
    assert_manylinux("manylinux2014_x86_64")

    # The modern open-ended glibc version based manylinux standards should be supported.
    assert_manylinux("manylinux_2_5_x86_64")
    assert_manylinux("manylinux_2_33_x86_64")

    target_configuration = compute_target_configuration(parser, args=["--no-manylinux"])
    assert target_configuration.assume_manylinux is None

    with pytest.raises(ArgumentTypeError):
        compute_target_configuration(parser, args=["--manylinux", "foo"])


def test_configure_platform(parser):
    # type: (ArgumentParser) -> None
    target_options.register(parser)

    def assert_platforms(
        platforms,  # type: Iterable[str]
        *expected_platforms  # type: Optional[Platform]
    ):
        # type: (...) -> None
        args = list(itertools.chain.from_iterable(("--platform", p) for p in platforms))
        target_configuration = compute_target_configuration(parser, args)
        assert not target_configuration.interpreters
        assert expected_platforms == target_configuration.platforms

    # The special 'current' platform should map to a `None` platform entry.
    assert_platforms(["current"], None)

    assert_platforms(["linux-x86_64-cp-37-cp37m"], Platform.create("linux-x86_64-cp-37-cp37m"))
    assert_platforms(["linux-x86_64-cp-37-m"], Platform.create("linux-x86_64-cp-37-cp37m"))
    assert_platforms(
        ["linux-x86_64-cp-37-m", "macosx-10.13-x86_64-cp-36-cp36m"],
        Platform.create("linux-x86_64-cp-37-cp37m"),
        Platform.create("macosx-10.13-x86_64-cp-36-m"),
    )


def assert_interpreters_configured(
    target_configuration,  # type: TargetConfiguration
    expected_interpreter,  # type: Optional[PythonInterpreter]
    expected_interpreters=None,  # type: Optional[Tuple[PythonInterpreter, ...]]
):
    # type: (...) -> None
    if expected_interpreter is None:
        assert target_configuration.interpreter is None
        assert not expected_interpreters
        return

    assert expected_interpreter == target_configuration.interpreter
    if expected_interpreters:
        assert expected_interpreter in expected_interpreters
        assert expected_interpreters == target_configuration.interpreters
    else:
        assert (expected_interpreter,) == target_configuration.interpreters


def assert_interpreter(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
    expected_interpreter,  # type: Optional[PythonInterpreter]
    *expected_interpreters  # type: PythonInterpreter
):
    # type: (...) -> None
    target_configuration = compute_target_configuration(parser, args=args)
    assert not target_configuration.platforms
    assert_interpreters_configured(
        target_configuration, expected_interpreter, expected_interpreters
    )


def test_configure_interpreter_empty(parser):
    # type: (ArgumentParser) -> None
    target_options.register(parser)
    assert_interpreter(parser, args=[], expected_interpreter=None)


def path_for(*interpreters):
    # type: (*PythonInterpreter) -> str
    return os.pathsep.join(os.path.dirname(interpreter.binary) for interpreter in interpreters)


def test_configure_interpreter_path(
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    with environment_as(PATH=path_for(py27, py37, py310)):
        assert_interpreter(parser, ["--python", "python"], py27)
        assert_interpreter(parser, ["--python", "python2"], py27)
        assert_interpreter(parser, ["--python", "python3"], py37)
        assert_interpreter(parser, ["--python", "python3.10"], py310)
        with pytest.raises(target_options.InterpreterNotFound):
            compute_target_configuration(parser, args=["--python", "python3.9"])


def test_configure_interpreter_pex_python_path(
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    path_env_var = path_for(py27, py37, py310)

    with ENV.patch(PEX_PYTHON_PATH=path_env_var):
        assert_interpreter(parser, ["--python", "python"], py27)
        assert_interpreter(parser, ["--python", "python2"], py27)
        assert_interpreter(parser, ["--python", "python3"], py37)
        assert_interpreter(parser, ["--python", "python3.10"], py310)
        with pytest.raises(target_options.InterpreterNotFound):
            compute_target_configuration(parser, args=["--python", "python3.9"])

    with ENV.patch(PEX_PYTHON_PATH=py27.binary):
        assert_interpreter(parser, ["--python", "python2.7"], py27)

    assert_interpreter(parser, ["--python-path", path_env_var, "--python", "python3"], py37)
    assert_interpreter(parser, ["--python-path", py310.binary, "--python", "python3.10"], py310)


def test_configure_interpreter_constraints(
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    path_env_var = path_for(py310, py27, py37)

    def interpreter_constraint_args(interpreter_constraints):
        # type: (Iterable[str]) -> List[str]
        args = ["--python-path", path_env_var]
        args.extend(
            itertools.chain.from_iterable(
                ("--interpreter-constraint", ic) for ic in interpreter_constraints
            )
        )
        return args

    def assert_interpreter_constraint(
        interpreter_constraints,  # type: Iterable[str]
        expected_interpreters,  # type: Iterable[PythonInterpreter]
        expected_interpreter,  # type: PythonInterpreter
    ):
        # type: (...) -> None
        assert_interpreter(
            parser,
            interpreter_constraint_args(interpreter_constraints),
            expected_interpreter,
            *expected_interpreters
        )

    assert_interpreter_constraint(["CPython"], [py310, py27, py37], expected_interpreter=py27)
    assert_interpreter_constraint([">=2"], [py310, py27, py37], expected_interpreter=py27)
    assert_interpreter_constraint([">=2,!=3.7.*"], [py310, py27], expected_interpreter=py27)
    assert_interpreter_constraint(["==3.*"], [py310, py37], expected_interpreter=py37)
    assert_interpreter_constraint(["==3.10.*"], [py310], expected_interpreter=py310)
    assert_interpreter_constraint([">3"], [py310, py37], expected_interpreter=py37)
    assert_interpreter_constraint([">=3.7,<3.8"], [py37], expected_interpreter=py37)
    assert_interpreter_constraint(["==3.10.*", "==2.7.*"], [py310, py27], expected_interpreter=py27)

    def assert_interpreter_constraint_not_satisfied(interpreter_constraints):
        # type: (List[str]) -> None
        with pytest.raises(target_options.InterpreterConstraintsNotSatisfied):
            compute_target_configuration(
                parser, interpreter_constraint_args(interpreter_constraints)
            )

    assert_interpreter_constraint_not_satisfied(["==3.9.*"])
    assert_interpreter_constraint_not_satisfied(["==3.8.*,!=3.8.*"])
    assert_interpreter_constraint_not_satisfied(["==3.9.*", "==2.6.*"])


def test_configure_resolve_local_platforms(
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    path_env_var = path_for(py27, py37, py310)

    def assert_local_platforms(
        platforms,  # type: Iterable[str]
        expected_platforms,  # type: Iterable[str]
        expected_interpreter,  # type: PythonInterpreter
        expected_interpreters=None,  # type: Optional[Tuple[PythonInterpreter, ...]]
        extra_args=None,  # type: Optional[Iterable[str]]
    ):
        # type: (...) -> None
        args = ["--python-path", path_env_var, "--resolve-local-platforms"]
        args.extend(itertools.chain.from_iterable(("--platform", p) for p in platforms))
        args.extend(extra_args or ())
        target_configuration = compute_target_configuration(parser, args)
        assert (
            tuple(Platform.create(ep) for ep in expected_platforms)
            == target_configuration.platforms
        )
        assert_interpreters_configured(
            target_configuration, expected_interpreter, expected_interpreters
        )

    assert_local_platforms(
        platforms=[str(py27.platform)],
        expected_platforms=(),
        expected_interpreter=py27,
    )

    foreign_platform = "linux-x86_64-cp-37-m" if IS_MAC else "macosx-10.13-x86_64-cp-37-m"

    assert_local_platforms(
        platforms=[foreign_platform, str(py37.platform)],
        expected_platforms=[foreign_platform],
        expected_interpreter=py37,
    )

    assert_local_platforms(
        platforms=[foreign_platform, str(py37.platform)],
        extra_args=["--interpreter-constraint", "CPython"],
        expected_platforms=[foreign_platform],
        expected_interpreter=py27,
        expected_interpreters=(py27, py37, py310),
    )

    assert_local_platforms(
        platforms=[foreign_platform, str(py27.platform)],
        extra_args=["--interpreter-constraint", "==3.10.*"],
        expected_platforms=[foreign_platform],
        expected_interpreter=py27,
        expected_interpreters=(py310, py27),
    )
