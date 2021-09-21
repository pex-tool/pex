# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import ArgumentParser

from pex.commands.command import JsonMixin, Ok, OutputMixin, Result
from pex.pex import PEX
from pex.tools.command import PEXCommand


class Info(JsonMixin, OutputMixin, PEXCommand):
    """Dumps the PEX-INFO json contained in a PEX file."""

    @classmethod
    def add_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        cls.add_output_option(parser, entity="PEX-INFO json")
        cls.add_json_options(parser, entity="PEX-INFO")
        cls.register_global_arguments(parser)

    def run(self, pex):
        # type: (PEX) -> Result
        with self.output(self.options) as out:
            self.dump_json(self.options, pex.pex_info().as_json_dict(), out)
            out.write("\n")
        return Ok()
