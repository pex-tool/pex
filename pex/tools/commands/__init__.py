# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.tools.command import Command
from pex.tools.commands.graph import Graph
from pex.tools.commands.info import Info
from pex.tools.commands.interpreter import Interpreter
from pex.tools.commands.venv import Venv
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable


def all_commands():
    # type: () -> Iterable[Command]
    return Info(), Interpreter(), Graph(), Venv()
