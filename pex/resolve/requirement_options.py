# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Namespace, _ActionsContainer

from pex.orderedset import OrderedSet
from pex.requirements import LocalProjectRequirement, ParseError, parse_requirement_string
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, List


def register(
    parser,  # type: _ActionsContainer
    include_positional_requirements=True,  # type: bool
    include_short_editable_switch=True,  # type: bool
):
    # type: (...) -> None
    """Register resolve requirement configuration options with the given parser.

    :param parser: The parser to register requirement configuration options with.
    :param include_positional_requirements: `True` to include a requirements option to gather
                                            positional args as extra requirements.
    :param include_short_editable_switch: `True` to include a `-e` switch for the `--editable`
                                          option.
    """
    if include_positional_requirements:
        parser.add_argument("requirements", nargs="*", help="Requirements to add to the pex")

    editable_flags = []  # type: List[str]
    if include_short_editable_switch:
        editable_flags.append("-e")
    editable_flags.append("--editable")

    parser.add_argument(
        *editable_flags,
        dest="editable_requirements",
        metavar="REQUIREMENT",
        default=[],
        type=str,
        action="append",
        help=(
            "Add the given requirement as editable. The requirement should be a path to a local "
            "project or else a direct reference to a local directory URL."
        )
    )
    parser.add_argument(
        "-r",
        "--requirement",
        "--requirements",
        "--with-requirements",
        dest="requirement_files",
        metavar="FILE or URL",
        default=[],
        type=str,
        action="append",
        help=(
            "Add requirements from the given requirements file.  This option can be used multiple "
            "times."
        ),
    )
    parser.add_argument(
        "--constraint",
        "--constraints",
        dest="constraint_files",
        metavar="FILE or URL",
        default=[],
        type=str,
        action="append",
        help=(
            "Add constraints from the given constraints file.  This option can be used multiple "
            "times."
        ),
    )


class InvalidConfigurationError(Exception):
    """Indicates an invalid requirements configuration."""


def configure(
    options,  # type: Namespace
    additional_requirements=(),  # type: Iterable[str]
):
    # type: (...) -> RequirementConfiguration
    """Creates a requirement configuration from options registered by `register`."""

    requirements = OrderedSet(getattr(options, "requirements", ()))  # type: OrderedSet[str]
    for editable_requirement in options.editable_requirements:
        try:
            parsed_requirement = parse_requirement_string(editable_requirement)
        except ParseError:
            raise InvalidConfigurationError(
                "Only local project directories can be resolved as editable; "
                "given {editable_requirement} which does not point to a local Python project "
                "directory.".format(editable_requirement=editable_requirement)
            )
        if not isinstance(parsed_requirement, LocalProjectRequirement):
            raise InvalidConfigurationError(
                "Only local project directories can be resolved as editable; "
                "given: {editable_requirement}".format(editable_requirement=editable_requirement)
            )
        if parsed_requirement.editable:
            raise InvalidConfigurationError(
                "Given nested editable requirement. "
                "Remove the nested editable flag: {editable_requirement}".format(
                    editable_requirement=editable_requirement
                )
            )
        requirements.add(
            "-e {editable_requirement}".format(editable_requirement=editable_requirement)
        )
    requirements.update(additional_requirements)

    return RequirementConfiguration(
        requirements=tuple(requirements),
        requirement_files=options.requirement_files,
        constraint_files=options.constraint_files,
    )
