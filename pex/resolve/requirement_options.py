# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import Namespace, _ActionsContainer

from pex.resolve.requirement_configuration import RequirementConfiguration


def register(parser):
    # type: (_ActionsContainer) -> None
    """Register resolve requirement configuration options with the given parser.

    :param parser: The parser to register requirement configuration options with.
    """

    parser.add_argument("requirements", nargs="*", help="Requirements to add to the pex")
    parser.add_argument(
        "-r",
        "--requirement",
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


def configure(options):
    # type: (Namespace) -> RequirementConfiguration
    """Creates a requirement configuration from options registered by `register`."""

    return RequirementConfiguration(
        requirements=options.requirements,
        requirement_files=options.requirement_files,
        constraint_files=options.constraint_files,
    )
