# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Namespace, _ActionsContainer

from pex.orderedset import OrderedSet
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable


def register(
    parser,  # type: _ActionsContainer
    include_positional_requirements=True,  # type: bool
):
    # type: (...) -> None
    """Register resolve requirement configuration options with the given parser.

    :param parser: The parser to register requirement configuration options with.
    :param include_positional_requirements: `True` to include a requirements option to gather
                                            positional args as extra requirements.
    """
    if include_positional_requirements:
        parser.add_argument("requirements", nargs="*", help="Requirements to add to the pex")
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


def configure(
    options,  # type: Namespace
    additional_requirements=(),  # type: Iterable[str]
):
    # type: (...) -> RequirementConfiguration
    """Creates a requirement configuration from options registered by `register`."""

    return RequirementConfiguration(
        requirements=OrderedSet(
            getattr(options, "requirements", []) + list(additional_requirements)
        ),
        requirement_files=options.requirement_files,
        constraint_files=options.constraint_files,
    )
