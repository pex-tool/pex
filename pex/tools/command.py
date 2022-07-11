# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from abc import abstractmethod

from pex.commands.command import Command
from pex.pex import PEX
from pex.result import Result


class PEXCommand(Command):
    @abstractmethod
    def run(self, pex):
        # type: (PEX) -> Result
        raise NotImplementedError()
