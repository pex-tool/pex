# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys
from argparse import ArgumentTypeError, Namespace, _ActionsContainer

from pex.argparse import HandleBoolAction
from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.orderedset import OrderedSet
from pex.platforms import Platform
from pex.resolve.resolver_options import _ManylinuxAction
from pex.resolve.target_configuration import TargetConfiguration


def register(parser):
    # type: (_ActionsContainer) -> None
    """Register resolve target selection options with the given parser.

    :param parser: The parser to register target selection options with.
    """

    parser.add_argument(
        "--python",
        dest="python",
        default=[],
        type=str,
        action="append",
        help=(
            "The Python interpreter to use to build the PEX (default: current interpreter). This "
            "cannot be used with `--interpreter-constraint`, which will instead cause PEX to "
            "search for valid interpreters. Either specify an absolute path to an interpreter, or "
            "specify a binary accessible on $PATH like `python3.7`. This option can be passed "
            "multiple times to create a multi-interpreter compatible PEX."
        ),
    )
    parser.add_argument(
        "--python-path",
        dest="python_path",
        default=None,
        type=str,
        help=(
            "Colon-separated paths to search for interpreters when `--interpreter-constraint` "
            "and/or `--resolve-local-platforms` are specified (default: $PATH). Each element "
            "can be the absolute path of an interpreter binary or a directory containing "
            "interpreter binaries."
        ),
    )

    current_interpreter = PythonInterpreter.get()
    program = sys.argv[0]
    singe_interpreter_info_cmd = (
        "PEX_TOOLS=1 {current_interpreter} {program} interpreter --verbose --indent 4".format(
            current_interpreter=current_interpreter.binary, program=program
        )
    )
    all_interpreters_info_cmd = (
        "PEX_TOOLS=1 {program} interpreter --all --verbose --indent 4".format(program=program)
    )

    parser.add_argument(
        "--interpreter-constraint",
        dest="interpreter_constraint",
        default=[],
        type=str,
        action="append",
        help=(
            "Constrain the selected Python interpreter. Specify with Requirement-style syntax, "
            'e.g. "CPython>=2.7,<3" (A CPython interpreter with version >=2.7 AND version <3), '
            '">=2.7,<3" (Any Python interpreter with version >=2.7 AND version <3) or "PyPy" (A '
            "PyPy interpreter of any version). This argument may be repeated multiple times to OR "
            "the constraints. Try `{singe_interpreter_info_cmd}` to find the exact interpreter "
            "constraints of {current_interpreter} and `{all_interpreters_info_cmd}` to find out "
            "the interpreter constraints of all Python interpreters on the $PATH.".format(
                current_interpreter=current_interpreter.binary,
                singe_interpreter_info_cmd=singe_interpreter_info_cmd,
                all_interpreters_info_cmd=all_interpreters_info_cmd,
            )
        ),
    )

    parser.add_argument(
        "--platform",
        dest="platforms",
        default=[],
        type=str,
        action="append",
        help=(
            "The platform for which to build the PEX. This option can be passed multiple times "
            "to create a multi-platform pex. To use the platform corresponding to the current "
            "interpreter you can pass `current`. To target any other platform you pass a string "
            "composed of fields: <platform>-<python impl abbr>-<python version>-<abi>. "
            "These fields stem from wheel name conventions as outlined in "
            "https://www.python.org/dev/peps/pep-0427#file-name-convention and influenced by "
            "https://www.python.org/dev/peps/pep-0425. For the current interpreter at "
            "{current_interpreter} the full platform string is {current_platform}. To find out "
            "more, try `{all_interpreters_info_cmd}` to print out the platform for all "
            "interpreters on the $PATH or `{singe_interpreter_info_cmd}` to inspect the single "
            "interpreter {current_interpreter}.".format(
                current_interpreter=current_interpreter.binary,
                current_platform=current_interpreter.platform,
                singe_interpreter_info_cmd=singe_interpreter_info_cmd,
                all_interpreters_info_cmd=all_interpreters_info_cmd,
            )
        ),
    )

    default_target_configuration = TargetConfiguration()
    parser.add_argument(
        "--manylinux",
        "--no-manylinux",
        "--no-use-manylinux",
        dest="assume_manylinux",
        type=str,
        default=default_target_configuration.assume_manylinux,
        action=_ManylinuxAction,
        help="Whether to allow resolution of manylinux wheels for linux target platforms.",
    )

    parser.add_argument(
        "--resolve-local-platforms",
        dest="resolve_local_platforms",
        default=False,
        action=HandleBoolAction,
        help=(
            "When --platforms are specified, attempt to resolve a local interpreter that matches "
            "each platform specified. If found, use the interpreter to resolve distributions; if "
            "not (or if this option is not specified), resolve for each platform only allowing "
            "matching binary distributions and failing if only sdists or non-matching binary "
            "distributions can be found."
        ),
    )


def configure(options):
    # type: (Namespace) -> TargetConfiguration
    """Creates a target configuration from options registered by `register`.

    :param options: The target configuration options.
    """
    try:
        interpreter_constraints = tuple(
            OrderedSet(
                PythonIdentity.parse_requirement(interpreter_constraint)
                for interpreter_constraint in options.interpreter_constraint
            )
        )
    except ValueError as e:
        raise ArgumentTypeError(str(e))

    try:
        platforms = tuple(
            OrderedSet(
                Platform.create(platform) if platform and platform != "current" else None
                for platform in options.platforms
            )
        )
    except Platform.InvalidPlatformError as e:
        raise ArgumentTypeError(str(e))

    return TargetConfiguration(
        interpreter_constraints=interpreter_constraints,
        python_path=options.python_path,
        pythons=tuple(OrderedSet(options.python)),
        platforms=platforms,
        resolve_local_platforms=options.resolve_local_platforms,
        assume_manylinux=options.assume_manylinux,
    )
