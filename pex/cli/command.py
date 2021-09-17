# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from abc import abstractmethod

from pex.commands.command import Command, Result


class BuildTimeCommand(Command):
    @abstractmethod
    def run(self):
        # type: () -> Result
        raise NotImplementedError()
