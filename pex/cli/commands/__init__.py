# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.cli.command import BuildTimeCommand
from pex.cli.commands.cache.command import Cache
from pex.cli.commands.docs import Docs
from pex.cli.commands.interpreter import Interpreter
from pex.cli.commands.lock import Lock
from pex.cli.commands.venv import Venv
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Type


def all_commands():
    # type: () -> Iterable[Type[BuildTimeCommand]]
    return Cache, Docs, Interpreter, Lock, Venv
