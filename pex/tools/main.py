# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import functools
import logging
import os
import sys
from argparse import ArgumentParser, Namespace

from pex import pex_bootstrapper
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.tools import commands
from pex.tools.command import Result
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Callable, NoReturn, Optional

    CommandFunc = Callable[[PEX, Namespace], Result]


def show_help(
    parser,  # type: ArgumentParser
    *_args,  # type: Any
    **_kwargs  # type: Any
):
    # type: (...) -> NoReturn
    parser.error("a subcommand is required")


def simplify_pex_path(pex_path):
    # type: (str) -> str
    # Generate the most concise path possible that is still cut/paste-able to the command line.
    pex_path = os.path.abspath(pex_path)
    cwd = os.getcwd()
    if os.path.commonprefix((pex_path, cwd)) == cwd:
        pex_path = os.path.relpath(pex_path, cwd)
        # Handle users that do not have . as a PATH entry.
        if not os.path.dirname(pex_path) and os.curdir not in os.environ.get("PATH", "").split(
            os.pathsep
        ):
            pex_path = os.path.join(os.curdir, pex_path)
    return pex_path


def main(
    pex=None,  # type: Optional[PEX]
    pex_prog_path=None,  # type: Optional[str]
):
    # type: (...) -> int
    logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
    with TRACER.timed("Executing PEX_TOOLS"):
        pex_prog_path = simplify_pex_path(pex_prog_path or pex.path()) if pex else None
        prog = (
            "PEX_TOOLS=1 {pex_path}".format(pex_path=pex_prog_path)
            if pex
            else "{python} {module}".format(
                python=sys.executable, module=".".join(__name__.split(".")[:-1])
            )
        )
        parser = ArgumentParser(
            prog=prog,
            description="Tools for working with {}.".format(pex_prog_path if pex else "PEX files"),
        )
        if pex is None:
            parser.add_argument(
                "pex", nargs=1, metavar="PATH", help="The path of the PEX file to operate on."
            )
        parser.set_defaults(func=functools.partial(show_help, parser))
        subparsers = parser.add_subparsers(
            description="{} can be operated on using any of the following subcommands.".format(
                "The PEX file {}".format(pex_prog_path) if pex else "A PEX file"
            ),
        )
        for command in commands.all_commands():
            name = command.__class__.__name__.lower()
            # N.B.: We want to trigger the default argparse description if the doc string is empty.
            description = command.__doc__ or None
            help_text = description.splitlines()[0] if description else None
            command_parser = subparsers.add_parser(name, help=help_text, description=description)
            command.add_arguments(command_parser)
            command_parser.set_defaults(func=command.run)

        options = parser.parse_args()
        if pex is None:
            pex_info = PexInfo.from_pex(options.pex[0])
            pex_info.update(PexInfo.from_env())
            interpreter = pex_bootstrapper.find_compatible_interpreter(
                interpreter_constraints=pex_info.interpreter_constraints
            )
            pex = PEX(options.pex[0], interpreter=interpreter)

        func = cast("CommandFunc", options.func)
        result = func(pex, options)
        result.maybe_display()
        return result.exit_code
