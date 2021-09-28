# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
from argparse import ArgumentParser, Namespace

from pex import pex_bootstrapper
from pex.commands.command import GlobalConfigurationError, Main, Result, catch
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.tools import commands
from pex.tools.command import PEXCommand
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Optional, Union

    CommandFunc = Callable[[PEX, Namespace], Result]


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


class PexTools(Main[PEXCommand]):
    def __init__(self, pex=None):
        # type: (Optional[PEX]) -> None

        pex_prog_path = simplify_pex_path(pex.path()) if pex else None

        # By default, let argparse derive prog from sys.argv[0].
        prog = None  # type: Optional[str]
        if pex:
            prog = "PEX_TOOLS=1 {pex_path}".format(pex_path=pex_prog_path)

        description = "Tools for working with {}.".format(pex_prog_path if pex else "PEX files")
        subparsers_description = (
            "{} can be operated on using any of the following subcommands.".format(
                "The PEX file {}".format(pex_prog_path) if pex else "A PEX file"
            )
        )

        super(PexTools, self).__init__(
            description=description,
            subparsers_description=subparsers_description,
            command_types=commands.all_commands(),
            prog=prog,
        )
        self._pex = pex

    def add_arguments(self, parser):
        # type: (ArgumentParser) -> None
        if self._pex is None:
            parser.add_argument(
                "pex", nargs=1, metavar="PATH", help="The path of the PEX file to operate on."
            )


def main(pex=None):
    # type: (Optional[PEX]) -> Union[int, str]

    pex_tools = PexTools(pex=pex)
    try:
        with pex_tools.parsed_command() as pex_command, TRACER.timed(
            "Executing PEX_TOOLS {}".format(pex_command.name())
        ):
            if pex is None:
                pex_file_path = pex_command.options.pex[0]
                pex_info = PexInfo.from_pex(pex_file_path)
                pex_info.update(PexInfo.from_env())
                interpreter = pex_bootstrapper.find_compatible_interpreter(
                    interpreter_constraints=pex_info.interpreter_constraints
                )
                pex = PEX(pex_file_path, interpreter=interpreter)

            result = catch(pex_command.run, pex)
            result.maybe_display()
            return result.exit_code
    except GlobalConfigurationError as e:
        return str(e)
