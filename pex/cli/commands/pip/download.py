# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
from argparse import _ActionsContainer

from pex.cli.command import BuildTimeCommand
from pex.cli.commands.pip import core
from pex.common import safe_copy, safe_mkdir
from pex.result import Ok, Result, try_


class Download(BuildTimeCommand):
    """Download distributions instead of resolving them into a PEX."""

    @classmethod
    def add_extra_arguments(cls, parser):
        # type: (_ActionsContainer) -> None
        parser.add_argument(
            "-d",
            "--dest-dir",
            metavar="PATH",
            required=True,
            help="The path to download distributions to.",
        )
        core.register_options(parser)

    def run(self):
        # type: () -> Result

        configuration = core.configure(self.options)
        dists = try_(core.download_distributions(configuration))

        safe_mkdir(self.options.dest_dir)
        for dist in dists:
            safe_copy(dist.path, os.path.join(self.options.dest_dir, os.path.basename(dist.path)))

        return Ok()
