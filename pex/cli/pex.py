# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.cli import commands
from pex.cli.command import BuildTimeCommand
from pex.commands.command import GlobalConfigurationError, Main
from pex.result import catch
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Union


class Pex3(Main[BuildTimeCommand]):
    """Tools for building and working with [P]ython [EX]ecutables.

    N.B: This interface is considered unstable until the release of Pex 3.0 at which point it will
    replace the current `pex` command.
    """


def main():
    # type: () -> Union[int, str]

    pex3 = Pex3(command_types=commands.all_commands())
    try:
        with pex3.parsed_command() as command:
            result = catch(command.run)
            result.maybe_display()
            return result.exit_code
    except GlobalConfigurationError as e:
        return str(e)
