# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import json
import os
import re
from argparse import ArgumentParser, ArgumentTypeError

import pytest

import pex.resolve.target_configuration
from pex.common import environment_as
from pex.interpreter import PythonInterpreter
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform
from pex.resolve import abbreviated_platforms, target_options
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.target_configuration import InterpreterConstraintsNotSatisfied
from pex.targets import CompletePlatform, Targets
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from testing import IS_MAC

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, List, Optional, Tuple, Type


def compute_target_configuration(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
):
    # type: (...) -> Targets
    options = parser.parse_args(args=args)
    return target_options.configure(options, pip_configuration=PipConfiguration()).resolve_targets()


def test_clp_manylinux(parser):
    # type: (ArgumentParser) -> None
    target_options.register(parser)

    assert compute_target_configuration(parser, args=[]) is not None

    def assert_manylinux(value):
        # type: (str) -> None
        assert compute_target_configuration(parser, args=["--manylinux", value]) is not None

    # Legacy manylinux standards should be supported.
    assert_manylinux("manylinux1_x86_64")
    assert_manylinux("manylinux2010_x86_64")
    assert_manylinux("manylinux2014_x86_64")

    # The modern open-ended glibc version based manylinux standards should be supported.
    assert_manylinux("manylinux_2_5_x86_64")
    assert_manylinux("manylinux_2_33_x86_64")

    assert compute_target_configuration(parser, args=["--no-manylinux"]) is not None

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
        targets = compute_target_configuration(parser, args)
        assert not targets.interpreters
        assert expected_platforms == targets.platforms

    assert_platforms([])

    # The special 'current' platform should map to a `None` platform entry.
    assert_platforms(["current"], None)

    assert_platforms(
        ["linux-x86_64-cp-37-cp37m"], abbreviated_platforms.create("linux-x86_64-cp-37-cp37m")
    )
    assert_platforms(
        ["linux-x86_64-cp-37-m"], abbreviated_platforms.create("linux-x86_64-cp-37-cp37m")
    )
    assert_platforms(
        ["linux-x86_64-cp-37-m", "macosx-10.13-x86_64-cp-36-cp36m"],
        abbreviated_platforms.create("linux-x86_64-cp-37-cp37m"),
        abbreviated_platforms.create("macosx-10.13-x86_64-cp-36-m"),
    )


def test_configure_complete_platform(
    tmpdir,  # type: Any
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
    current_interpreter,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    def parse_complete_platforms(*platforms):
        # type: (*str) -> Targets
        args = list(itertools.chain.from_iterable(("--complete-platform", p) for p in platforms))
        return compute_target_configuration(parser, args)

    def assert_complete_platforms(
        platforms,  # type: Iterable[str]
        *expected_platforms  # type: CompletePlatform
    ):
        # type: (...) -> None
        targets = parse_complete_platforms(*platforms)
        assert not targets.interpreters
        assert expected_platforms == targets.complete_platforms

    def complete_platform_json(
        interpreter,  # type: PythonInterpreter
        **extra_fields  # type: Any
    ):
        # type: (...) -> str
        return json.dumps(
            dict(
                marker_environment=interpreter.identity.env_markers.as_dict(),
                compatible_tags=interpreter.identity.supported_tags.to_string_list(),
                **extra_fields
            )
        )

    def dump_complete_platform(
        interpreter,  # type: PythonInterpreter
        **extra_fields  # type: Any
    ):
        # type: (...) -> str
        path = os.path.join(str(tmpdir), interpreter.binary.replace(os.sep, ".").lstrip("."))
        with open(path, "w") as fp:
            fp.write(complete_platform_json(interpreter, **extra_fields))
        return path

    assert_complete_platforms([])

    assert_complete_platforms(
        [complete_platform_json(current_interpreter)],
        CompletePlatform.from_interpreter(current_interpreter),
    )
    assert_complete_platforms(
        [dump_complete_platform(current_interpreter)],
        CompletePlatform.from_interpreter(current_interpreter),
    )
    assert_complete_platforms(
        [dump_complete_platform(py310), complete_platform_json(py27)],
        CompletePlatform.from_interpreter(py310),
        CompletePlatform.from_interpreter(py27),
    )

    assert_complete_platforms(
        ['{"marker_environment": {}, "compatible_tags": ["py2.py3-none-any"], "ignored": 42}'],
        CompletePlatform.create(
            marker_environment=MarkerEnvironment(),
            supported_tags=CompatibilityTags.from_strings(["py2.py3-none-any"]),
        ),
    )

    def assert_argument_type_error(
        expected_message_prefix,  # type: str
        *platforms  # type: str
    ):
        # type: (...) -> None
        with pytest.raises(
            ArgumentTypeError,
            match=r"{}.*".format(re.escape(expected_message_prefix)),
        ):
            parse_complete_platforms(*platforms)

    assert_argument_type_error(
        "The complete platform JSON object did not have the required 'compatible_tags' key:",
        '{"marker_environment": {}}',
    )

    assert_argument_type_error(
        "The complete platform JSON object did not have the required 'marker_environment' " "key:",
        '{"compatible_tags": ["py2.py3-none-any"]}',
    )

    assert_argument_type_error(
        "Invalid environment entry provided:",
        '{"marker_environment": {"bad_key": "42"}, "compatible_tags": ["py2.py3-none-any"]}',
    )


def assert_interpreters_configured(
    targets,  # type: Targets
    expected_interpreter,  # type: Optional[PythonInterpreter]
    expected_interpreters=None,  # type: Optional[Tuple[PythonInterpreter, ...]]
):
    # type: (...) -> None
    if expected_interpreter is None:
        assert targets.interpreter is None
        assert not expected_interpreters
        return

    assert expected_interpreter == targets.interpreter
    if expected_interpreters:
        assert expected_interpreter in expected_interpreters
        assert expected_interpreters == targets.interpreters
    else:
        assert (expected_interpreter,) == targets.interpreters


def assert_interpreter(
    parser,  # type: ArgumentParser
    args,  # type: List[str]
    expected_interpreter,  # type: Optional[PythonInterpreter]
    *expected_interpreters  # type: PythonInterpreter
):
    # type: (...) -> None
    targets = compute_target_configuration(parser, args=args)
    assert not targets.platforms
    assert_interpreters_configured(targets, expected_interpreter, expected_interpreters)


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
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    with environment_as(PATH=path_for(py27, py38, py310)):
        assert_interpreter(parser, ["--python", "python"], py27)
        assert_interpreter(parser, ["--python", "python2"], py27)
        assert_interpreter(parser, ["--python", "python3"], py38)
        assert_interpreter(parser, ["--python", "python3.10"], py310)
        with pytest.raises(pex.resolve.target_configuration.InterpreterNotFound):
            compute_target_configuration(parser, args=["--python", "python3.9"])


def test_configure_interpreter_pex_python_path(
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    path_env_var = path_for(py27, py38, py310)

    with ENV.patch(PEX_PYTHON_PATH=path_env_var):
        assert_interpreter(parser, ["--python", "python"], py27)
        assert_interpreter(parser, ["--python", "python2"], py27)
        assert_interpreter(parser, ["--python", "python3"], py38)
        assert_interpreter(parser, ["--python", "python3.10"], py310)
        with pytest.raises(pex.resolve.target_configuration.InterpreterNotFound):
            compute_target_configuration(parser, args=["--python", "python3.9"])

    with ENV.patch(PEX_PYTHON_PATH=py27.binary):
        assert_interpreter(parser, ["--python", "python2.7"], py27)

    assert_interpreter(parser, ["--python-path", path_env_var, "--python", "python3"], py38)
    assert_interpreter(parser, ["--python-path", py310.binary, "--python", "python3.10"], py310)


def test_configure_interpreter_constraints(
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    path_env_var = path_for(py310, py27, py38)

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

    assert_interpreter_constraint(["CPython"], [py310, py27, py38], expected_interpreter=py27)
    assert_interpreter_constraint([">=2"], [py310, py27, py38], expected_interpreter=py27)
    assert_interpreter_constraint([">=2,!=3.8.*"], [py310, py27], expected_interpreter=py27)
    assert_interpreter_constraint(["==3.*"], [py310, py38], expected_interpreter=py38)
    assert_interpreter_constraint(["==3.10.*"], [py310], expected_interpreter=py310)
    assert_interpreter_constraint([">3"], [py310, py38], expected_interpreter=py38)
    assert_interpreter_constraint([">=3.8,<3.9"], [py38], expected_interpreter=py38)
    assert_interpreter_constraint(["==3.10.*", "==2.7.*"], [py310, py27], expected_interpreter=py27)

    def assert_interpreter_constraint_not_satisfied(
        interpreter_constraints,  # type: List[str]
        expected_error_type,  # type: Type[Exception]
    ):
        # type: (...) -> None
        with pytest.raises(expected_error_type):
            compute_target_configuration(
                parser, interpreter_constraint_args(interpreter_constraints)
            )

    assert_interpreter_constraint_not_satisfied(
        ["==3.9.*"], expected_error_type=InterpreterConstraintsNotSatisfied
    )
    assert_interpreter_constraint_not_satisfied(
        ["==3.8.*,!=3.8.*"], expected_error_type=ArgumentTypeError
    )
    assert_interpreter_constraint_not_satisfied(
        ["==3.9.*", "==2.6.*"], expected_error_type=InterpreterConstraintsNotSatisfied
    )


def test_configure_resolve_local_platforms(
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    path_env_var = path_for(py27, py38, py310)

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
        targets = compute_target_configuration(parser, args)
        assert (
            tuple(abbreviated_platforms.create(ep) for ep in expected_platforms)
            == targets.platforms
        )
        assert_interpreters_configured(targets, expected_interpreter, expected_interpreters)

    assert_local_platforms(
        platforms=[str(py27.platform)],
        expected_platforms=(),
        expected_interpreter=py27,
    )

    foreign_platform = "linux-x86_64-cp-37-m" if IS_MAC else "macosx-10.13-x86_64-cp-37-m"

    assert_local_platforms(
        platforms=[foreign_platform, str(py38.platform)],
        expected_platforms=[foreign_platform],
        expected_interpreter=py38,
    )

    assert_local_platforms(
        platforms=[foreign_platform, str(py38.platform)],
        extra_args=["--interpreter-constraint", "CPython"],
        expected_platforms=[foreign_platform],
        expected_interpreter=py27,
        expected_interpreters=(py27, py38, py310),
    )

    assert_local_platforms(
        platforms=[foreign_platform, str(py27.platform)],
        extra_args=["--interpreter-constraint", "==3.10.*"],
        expected_platforms=[foreign_platform],
        expected_interpreter=py27,
        expected_interpreters=(py310, py27),
    )


def test_configure_resolve_local_platforms_with_complete_platforms(
    tmpdir,  # type: Any
    parser,  # type: ArgumentParser
    py27,  # type: PythonInterpreter
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None
    target_options.register(parser)

    path_env_var = path_for(py27, py38, py310)

    def dump_complete_platform(
        name,  # type: str
        marker_environment,  # type: Dict[str, str]
        compatible_tags,  # type: List[str]
        **extra_fields  # type: Any
    ):
        # type: (...) -> str
        path = os.path.join(str(tmpdir), name)
        with open(path, "w") as fp:
            json.dump(
                dict(
                    marker_environment=marker_environment,
                    compatible_tags=compatible_tags,
                    **extra_fields
                ),
                fp,
            )
        return path

    def assert_local_platforms(
        complete_platforms,  # type: Iterable[str]
        expected_complete_platforms,  # type: Iterable[str]
        expected_interpreter,  # type: Optional[PythonInterpreter]
        expected_interpreters=None,  # type: Optional[Tuple[PythonInterpreter, ...]]
    ):
        # type: (...) -> None
        args = ["--python-path", path_env_var, "--resolve-local-platforms"]
        args.extend(
            itertools.chain.from_iterable(("--complete-platform", p) for p in complete_platforms)
        )
        targets = compute_target_configuration(parser, args)
        expected_complete_platform_objects = tuple(
            target_options._create_complete_platform(cp) for cp in expected_complete_platforms
        )
        assert expected_complete_platform_objects == targets.complete_platforms
        assert_interpreters_configured(targets, expected_interpreter, expected_interpreters)

    py38_complete = dump_complete_platform(
        "py38",
        py38.identity.env_markers.as_dict(),
        py38.identity.supported_tags.to_string_list(),
    )
    py38_extra_complete = dump_complete_platform(
        "py38_extra",
        py38.identity.env_markers.as_dict(),
        py38.identity.supported_tags.to_string_list() + ["py3-none-manylinux_2_9999_x86_64"],
    )

    py38_extra_complete_prefixed = dump_complete_platform(
        "py38_extra_prefixed",
        py38.identity.env_markers.as_dict(),
        ["py3-none-manylinux_2_9999_x86_64"] + py38.identity.supported_tags.to_string_list(),
    )

    py38_subset_tags = py38.identity.supported_tags.to_string_list()[:-10]
    # make the platform different
    py38_subset_tags[0:2] = py38_subset_tags[0:2:-1]
    py38_subset_complete = dump_complete_platform(
        "py38_subset",
        py38.identity.env_markers.as_dict(),
        py38_subset_tags,
    )
    py310_complete = dump_complete_platform(
        "py310",
        py310.identity.env_markers.as_dict(),
        py310.identity.supported_tags.to_string_list(),
    )
    py39999_env_markers = py310.identity.env_markers.as_dict()
    py39999_env_markers.update(
        implementation_version="3.9999.0",
        python_full_version="3.9999.0",
        python_version="3.9999",
        sys_platform="linux",
    )
    py39999_complete = dump_complete_platform(
        "other",
        py39999_env_markers,
        [
            "py39999-none-any",
            "py3-none-any",
            "py39998-none-any",
            "py39997-none-any",
            # you get the idea...
            "py310-none-any",
            "py39-none-any",
            "py38-none-any",
            "py37-none-any",
            "py36-none-any",
            "py35-none-any",
            "py34-none-any",
            "py33-none-any",
            "py32-none-any",
            "py31-none-any",
            "py30-none-any",
        ],
    )

    # exact match, yay
    assert_local_platforms(
        complete_platforms=[py38_complete],
        expected_complete_platforms=[],
        expected_interpreter=py38,
    )

    # the interpreter doesn't support some tags, but that's fine
    assert_local_platforms(
        complete_platforms=[py38_extra_complete],
        expected_complete_platforms=[],
        expected_interpreter=py38,
    )

    # the interpreter doesn't support some more specific tags, that is also fine
    assert_local_platforms(
        complete_platforms=[py38_extra_complete_prefixed],
        expected_complete_platforms=[],
        expected_interpreter=py38,
    )

    # # the interpreter has some tags it supports that this complete platform does not
    assert_local_platforms(
        complete_platforms=[py38_subset_complete],
        expected_complete_platforms=[py38_subset_complete],
        expected_interpreter=None,
    )

    # as above, but now with multiple complete platforms that apply to one interpreter (two
    # compatible, one not)
    assert_local_platforms(
        complete_platforms=[py38_subset_complete, py38_complete, py38_extra_complete],
        expected_complete_platforms=[py38_subset_complete],
        expected_interpreter=py38,  # compatible with py38_complete and py38_extra_complete
    )

    # wildly different
    assert_local_platforms(
        complete_platforms=[py39999_complete],
        expected_complete_platforms=[py39999_complete],
        expected_interpreter=None,
    )

    # multiple
    assert_local_platforms(
        complete_platforms=[py38_complete, py310_complete],
        expected_complete_platforms=[],
        expected_interpreter=py38,
        expected_interpreters=(py38, py310),
    )
