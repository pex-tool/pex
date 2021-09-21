# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.cli.command import BuildTimeCommand
from pex.commands.command import GlobalConfigurationError, Main
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Union


class Pex3(Main[BuildTimeCommand]):
    pass


def main():
    # type: () -> Union[int, str]

    pex3 = Pex3(
        description="Tools for building and working with [P]ython [EX]ecutables..",
        command_types=(),
    )
    try:
        with pex3.parsed_command() as command:
            result = command.run()
            result.maybe_display()
            return result.exit_code
    except GlobalConfigurationError as e:
        return str(e)
