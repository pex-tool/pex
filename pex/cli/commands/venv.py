# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from argparse import ArgumentParser, _ActionsContainer

from pex.cli.command import BuildTimeCommand
from pex.commands.command import JsonMixin, OutputMixin
from pex.common import is_script
from pex.pex_info import PexInfo
from pex.result import Error, Ok, Result
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any, Dict


class Venv(OutputMixin, JsonMixin, BuildTimeCommand):
    @classmethod
    def _add_inspect_arguments(cls, parser):
        # type: (_ActionsContainer) -> None
        parser.add_argument(
            "venv",
            help="The path of either the venv directory or its Python interpreter.",
        )
        cls.add_output_option(parser, entity="venv information")
        cls.add_json_options(parser, entity="venv information")

    @classmethod
    def add_extra_arguments(
        cls,
        parser,  # type: ArgumentParser
    ):
        # type: (...) -> None
        subcommands = cls.create_subcommands(
            parser,
            description="Interact with virtual environments via the following subcommands.",
        )
        with subcommands.parser(
            name="inspect",
            help="Inspect an existing venv.",
            func=cls._inspect,
            include_verbosity=False,
        ) as inspect_parser:
            cls._add_inspect_arguments(inspect_parser)

    def _inspect(self):
        # type: () -> Result

        venv = self.options.venv
        if not os.path.exists(venv):
            return Error("The given venv path of {venv} does not exist.".format(venv=venv))

        if os.path.isdir(venv):
            virtualenv = Virtualenv(os.path.normpath(venv))
            if not virtualenv.interpreter.is_venv:
                return Error("{venv} is not a venv.".format(venv=venv))
        else:
            maybe_venv = Virtualenv.enclosing(os.path.normpath(venv))
            if not maybe_venv:
                return Error("{python} is not an venv interpreter.".format(python=venv))
            virtualenv = maybe_venv

        try:
            pex = PexInfo.from_pex(virtualenv.venv_dir)
            is_pex = True
            pex_version = pex.build_properties.get("pex_version")
        except (IOError, OSError, ValueError):
            is_pex = False
            pex_version = None

        venv_info = dict(
            venv_dir=virtualenv.venv_dir,
            provenance=dict(
                created_by=virtualenv.created_by,
                is_pex=is_pex,
                pex_version=pex_version,
            ),
            include_system_site_packages=virtualenv.include_system_site_packages,
            interpreter=dict(
                binary=virtualenv.interpreter.binary,
                base_binary=virtualenv.interpreter.resolve_base_interpreter().binary,
                version=virtualenv.interpreter.identity.version_str,
                sys_path=virtualenv.sys_path,
            ),
            script_dir=virtualenv.bin_dir,
            scripts=sorted(
                os.path.relpath(exe, virtualenv.bin_dir)
                for exe in virtualenv.iter_executables()
                if is_script(exe)
            ),
            site_packages=virtualenv.site_packages_dir,
            distributions=sorted(
                str(dist.as_requirement()) for dist in virtualenv.iter_distributions()
            ),
        )  # type: Dict[str, Any]

        with self.output(self.options) as out:
            self.dump_json(self.options, venv_info, out)
            out.write("\n")

        return Ok()
