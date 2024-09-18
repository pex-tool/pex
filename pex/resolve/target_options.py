# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os.path
import sys
from argparse import ArgumentTypeError, Namespace, _ActionsContainer

from pex.argparse import HandleBoolAction
from pex.interpreter_constraints import InterpreterConstraints
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform, PlatformSpec
from pex.resolve import abbreviated_platforms
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.resolver_options import _ManylinuxAction
from pex.resolve.target_configuration import InterpreterConfiguration, TargetConfiguration
from pex.targets import CompletePlatform
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


def register(
    parser,  # type: _ActionsContainer
    include_platforms=True,  # type: bool
):
    # type: (...) -> None
    """Register resolve target selection options with the given parser.

    :param parser: The parser to register target selection options with.
    :param include_platforms: Whether to include options to select targets by platform.
    """

    parser.add_argument(
        "--python",
        dest="python",
        default=[],
        type=str,
        action="append",
        help=(
            "The Python interpreter to use (default: current interpreter). Either specify an "
            "absolute path to an interpreter, or specify a binary accessible on $PATH like "
            "`python3.7`. This option can be passed multiple times."
        ),
    )
    parser.add_argument(
        "--python-path",
        dest="python_path",
        default=None,
        type=str,
        help=(
            "A {pathsep!r} separated list of paths to search for interpreters in when "
            "`--interpreter-constraint` {and_maybe_platforms} specified (default: $PATH). Each "
            "element can be the absolute path of an interpreter binary or a directory containing "
            "interpreter binaries.".format(
                pathsep=os.pathsep,
                and_maybe_platforms=(
                    "and/or `--resolve-local-platforms` are" if include_platforms else "is"
                ),
            )
        ),
    )

    single_interpreter_info_cmd = (
        "pex3 interpreter inspect --python {current_interpreter} --verbose --indent 4".format(
            current_interpreter=sys.executable
        )
    )
    all_interpreters_info_cmd = "pex3 interpreter inspect --all --verbose --indent 4"

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
            "the constraints. Try `{single_interpreter_info_cmd}` to find the exact interpreter "
            "constraints of {current_interpreter} and `{all_interpreters_info_cmd}` to find out "
            "the interpreter constraints of all Python interpreters on the $PATH.".format(
                current_interpreter=sys.executable,
                single_interpreter_info_cmd=single_interpreter_info_cmd,
                all_interpreters_info_cmd=all_interpreters_info_cmd,
            )
        ),
    )

    if include_platforms:
        _register_platform_options(parser, single_interpreter_info_cmd, all_interpreters_info_cmd)


def _register_platform_options(
    parser,  # type: _ActionsContainer
    single_interpreter_info_cmd,  # type: str
    all_interpreters_info_cmd,  # type: str
):
    # type: (...) -> None
    parser.add_argument(
        "--platform",
        "--abbreviated-platform",
        dest="platforms",
        default=[],
        type=str,
        action="append",
        help=(
            "The (abbreviated) platform to build the PEX for. This option can be passed multiple "
            "times to create a multi-platform pex. To use the platform corresponding to the "
            "current interpreter you can pass `current`. To target any other platform you pass a "
            "string composed of fields: <platform>-<python impl abbr>-<python version>-<abi>. "
            "These fields stem from wheel name conventions as outlined in "
            "https://www.python.org/dev/peps/pep-0427#file-name-convention and influenced by "
            "https://www.python.org/dev/peps/pep-0425. To find out more, try "
            "`{all_interpreters_info_cmd}` to print out the platform for all interpreters on the "
            "$PATH or `{single_interpreter_info_cmd}` to inspect the single interpreter "
            "{current_interpreter}.".format(
                current_interpreter=sys.executable,
                single_interpreter_info_cmd=single_interpreter_info_cmd,
                all_interpreters_info_cmd=all_interpreters_info_cmd,
            )
        ),
    )

    parser.add_argument(
        "--complete-platform",
        dest="complete_platforms",
        default=[],
        type=str,
        action="append",
        help=(
            "The complete platform information describing the platform for which to build the PEX. "
            "This option can be passed multiple times to create a multi-platform pex. Values "
            "should be either JSON object literal strings or paths to files containing them. The "
            "JSON object is expected to have two fields with any other fields ignored. The "
            "'marker_environment' field should have an object value with string field values "
            "corresponding to PEP-508 marker environment entries (See: "
            "https://www.python.org/dev/peps/pep-0508/#environment-markers). It is OK to only have "
            "a subset of valid marker environment fields but it is not valid to present entries "
            "not defined in PEP-508. The 'compatible_tags' field should have an array of strings "
            "value containing the compatible tags in order from most specific first to least "
            "specific last as defined in PEP-425 (See: https://www.python.org/dev/peps/pep-0425). "
            "Pex can create complete platform JSON for you by running it on the target platform "
            "like so: `pex3 interpreter inspect --markers --tags`. For more options, particularly "
            "to select the desired target interpreter see: `pex3 interpreter inspect --help`."
        ),
    )

    parser.add_argument(
        "--manylinux",
        "--no-manylinux",
        "--no-use-manylinux",
        dest="assume_manylinux",
        type=str,
        default="manylinux2014",
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


def configure_interpreters(options):
    # type: (Namespace) -> InterpreterConfiguration
    """Creates an interpreter configuration from options registered by `register`.

    :param options: The interpreter configuration options.
    """
    try:
        interpreter_constraints = InterpreterConstraints.parse(*options.interpreter_constraint)
    except ValueError as e:
        raise ArgumentTypeError(str(e))

    return InterpreterConfiguration(
        interpreter_constraints=interpreter_constraints,
        python_path=(
            tuple(OrderedSet(options.python_path.split(os.pathsep)))
            if options.python_path
            else None
        ),
        pythons=tuple(OrderedSet(options.python)),
    )


def _create_complete_platform(value):
    # type: (str) -> CompletePlatform
    if os.path.isfile(value):
        try:
            with open(value) as fp:
                data = json.load(fp)
        except (OSError, ValueError) as e:
            raise ArgumentTypeError(
                "Failed to load complete platform data from {path}: {err}".format(path=value, err=e)
            )
    else:
        try:
            data = json.loads(value)
        except ValueError as e:
            raise ArgumentTypeError(
                "Failed to load complete platform data from json string: {err}".format(err=e)
            )

    try:
        marker_environment = MarkerEnvironment(**data["marker_environment"])
    except KeyError:
        raise ArgumentTypeError(
            "The complete platform JSON object did not have the required 'marker_environment' "
            "key:\n{json_object}".format(json_object=json.dumps(data, indent=4))
        )
    except TypeError as e:
        raise ArgumentTypeError(
            "Invalid environment entry provided: {err}\n"
            "See https://www.python.org/dev/peps/pep-0508/#environment-markers for valid "
            "entries.".format(err=e)
        )

    try:
        supported_tags = CompatibilityTags.from_strings(data["compatible_tags"])
    except KeyError:
        raise ArgumentTypeError(
            "The complete platform JSON object did not have the required 'compatible_tags' "
            "key:\n{json_object}".format(json_object=json.dumps(data, indent=4))
        )

    return CompletePlatform.create(marker_environment, supported_tags)


def configure(
    options,  # type: Namespace
    pip_configuration,  # type: PipConfiguration
):
    # type: (...) -> TargetConfiguration
    """Creates a target configuration from options via `register(..., include_platforms=True)`.

    :param options: The target configuration options.
    :param pip_configuration: The Pip configuration options.
    """
    interpreter_configuration = configure_interpreters(options)

    platforms = OrderedSet()  # type: OrderedSet[Optional[Platform]]
    if options.platforms:
        try:
            platforms.update(
                (
                    abbreviated_platforms.create(
                        platform,
                        manylinux=options.assume_manylinux,
                        pip_configuration=pip_configuration,
                    )
                    if platform and platform != "current"
                    else None
                )
                for platform in options.platforms
            )
        except PlatformSpec.InvalidSpecError as e:
            raise ArgumentTypeError(str(e))

    complete_platforms = tuple(
        OrderedSet(_create_complete_platform(value) for value in options.complete_platforms)
    )

    return TargetConfiguration(
        interpreter_configuration=interpreter_configuration,
        platforms=tuple(platforms),
        complete_platforms=complete_platforms,
        resolve_local_platforms=options.resolve_local_platforms,
    )
