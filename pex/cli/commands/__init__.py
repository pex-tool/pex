# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.cli.command import BuildTimeCommand
from pex.cli.commands.lock import Lock
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Type


def all_commands():
    # type: () -> Iterable[Type[BuildTimeCommand]]
    return [Lock]
