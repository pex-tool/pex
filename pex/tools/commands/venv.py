# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
import os
from argparse import ArgumentParser

from pex.common import safe_delete, safe_rmtree
from pex.enum import Enum
from pex.pex import PEX
from pex.result import Error, Ok, Result
from pex.tools.command import PEXCommand
from pex.typing import TYPE_CHECKING
from pex.venv.bin_path import BinPath
from pex.venv.pex import populate_venv
from pex.venv.virtualenv import PipUnavailableError, Virtualenv

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RemoveScope(Enum["RemoveScope.Value"]):
    class Value(Enum.Value):
        pass

    PEX = Value("pex")
    PEX_AND_PEX_ROOT = Value("all")


class Venv(PEXCommand):
    """Creates a venv from the PEX file."""

    @classmethod
    def add_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        parser.add_argument(
            "venv",
            nargs=1,
            metavar="PATH",
            help="The directory to create the virtual environment in.",
        )
        parser.add_argument(
            "-b",
            "--bin-path",
            default=BinPath.FALSE.value,
            choices=BinPath.values(),
            type=BinPath.for_value,
            help="Add the venv bin dir to the PATH in the __main__.py script.",
        )
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            default=False,
            help="If the venv directory already exists, overwrite it.",
        )
        parser.add_argument(
            "--collisions-ok",
            action="store_true",
            default=False,
            help=(
                "Don't error if population of the venv encounters distributions in the PEX file "
                "with colliding files, just emit a warning."
            ),
        )
        parser.add_argument(
            "-p",
            "--pip",
            action="store_true",
            default=False,
            help="Add pip to the venv.",
        )
        parser.add_argument(
            "--copies",
            action="store_true",
            default=False,
            help="Create the venv using copies of system files instead of symlinks",
        )
        parser.add_argument(
            "--compile",
            action="store_true",
            default=False,
            help="Compile all `.py` files in the venv.",
        )
        parser.add_argument(
            "--prompt",
            help="A custom prompt for the venv activation scripts to use.",
        )
        parser.add_argument(
            "--rm",
            "--remove",
            dest="remove",
            default=None,
            choices=RemoveScope.values(),
            type=RemoveScope.for_value,
            help=(
                "Remove the PEX after creating a venv from it if the {pex!r} value is specified; "
                "otherwise, remove the PEX and the PEX_ROOT if the {all!r} value is "
                "specified.".format(
                    pex=RemoveScope.PEX.value, all=RemoveScope.PEX_AND_PEX_ROOT.value
                )
            ),
        )
        cls.register_global_arguments(parser, include_verbosity=False)

    def run(self, pex):
        # type: (PEX) -> Result

        venv_dir = self.options.venv[0]
        venv = Virtualenv.create(
            venv_dir,
            interpreter=pex.interpreter,
            force=self.options.force,
            copies=self.options.copies,
            prompt=self.options.prompt,
        )
        if self.options.prompt != venv.custom_prompt:
            logger.warning(
                "Unable to apply custom --prompt {prompt!r} in {python} venv; continuing with the "
                "default prompt.".format(
                    prompt=self.options.prompt, python=venv.interpreter.identity
                )
            )
        populate_venv(
            venv,
            pex,
            bin_path=self.options.bin_path,
            collisions_ok=self.options.collisions_ok,
            symlink=False,
        )
        if self.options.pip:
            try:
                venv.install_pip()
            except PipUnavailableError as e:
                return Error(
                    "The virtual environment was successfully created, but Pip was not "
                    "installed:\n{}".format(e)
                )
        if self.options.compile:
            pex.interpreter.execute(["-m", "compileall", venv_dir])
        if self.options.remove is not None:
            if os.path.isdir(pex.path()):
                safe_rmtree(pex.path())
            else:
                safe_delete(pex.path())
            if self.options.remove is RemoveScope.PEX_AND_PEX_ROOT:
                safe_rmtree(pex.pex_info().pex_root)
        return Ok()
