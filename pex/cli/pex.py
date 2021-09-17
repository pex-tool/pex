# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.cli.command import BuildTimeCommand
from pex.commands.command import Main


class Pex3(Main[BuildTimeCommand]):
    pass


def main():
    # type: () -> int

    pex3 = Pex3(
        description="Tools for building and working with [P]ython [EX]ecutables..",
        command_types=(),
    )
    command = pex3.parse_command()
    result = command.run()
    result.maybe_display()
    return result.exit_code
