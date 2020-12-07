# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import ArgumentParser, Namespace

from pex.pex import PEX
from pex.tools.command import Command, JsonMixin, Ok, OutputMixin, Result


class Info(JsonMixin, OutputMixin, Command):
    """Dumps the PEX-INFO json contained in a PEX file."""

    def add_arguments(self, parser):
        # type: (ArgumentParser) -> None
        self.add_output_option(parser, entity="PEX-INFO json")
        self.add_json_options(parser, entity="PEX-INFO")

    def run(
        self,
        pex,  # type: PEX
        options,  # type: Namespace
    ):
        # type: (...) -> Result
        with self.output(options) as out:
            self.dump_json(options, pex.pex_info().as_json_dict(), out)
            out.write("\n")
        return Ok()
