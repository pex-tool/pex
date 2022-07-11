# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
from argparse import ArgumentParser, _ActionsContainer

from pex.cli.command import BuildTimeCommand
from pex.commands.command import JsonMixin, OutputMixin
from pex.interpreter import PythonInterpreter
from pex.resolve import target_options
from pex.resolve.target_configuration import InterpreterConstraintsNotSatisfied, InterpreterNotFound
from pex.result import Error, Ok, Result
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict


logger = logging.getLogger(__name__)


class Interpreter(OutputMixin, JsonMixin, BuildTimeCommand):
    @classmethod
    def _add_inspect_arguments(cls, parser):
        # type: (_ActionsContainer) -> None
        cls.add_output_option(parser, entity="Python interpreter path")
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help=(
                "Provide more information about the interpreter in JSON format. Use --tags and "
                "--markers to include even more information. The 'path' key is guaranteed to be "
                "present at a minimum and will contain the path to the interpreter."
            ),
        )
        parser.add_argument(
            "-t",
            "--tags",
            "--compatible-tags",
            action="store_true",
            help=(
                "Include the interpreter's compatible tags in the verbose JSON output under the "
                "'compatible_tags' key with more preferable (more specific) tags ordered earlier. "
                "The 'path' key is guaranteed to be present and will contain the path to the "
                "interpreter."
            ),
        )
        parser.add_argument(
            "-m",
            "--markers",
            "--marker-env",
            "--marker-environment",
            action="store_true",
            help=(
                "Include the interpreter's PEP-508 marker environment in the verbose JSON output "
                "under the 'marker_environment' key. The 'path' key is guaranteed to be present "
                "and will contain the path to the interpreter."
            ),
        )
        cls.add_json_options(parser, entity="verbose output")

        interpreter_options_parser = parser.add_argument_group(
            title="Interpreter options",
            description=(
                "Specify which interpreters to inspect. The current interpreter is inspected "
                "by default."
            ),
        )
        interpreter_options_parser.add_argument(
            "-a",
            "--all",
            action="store_true",
            help="Print all compatible interpreters, preferred first.",
        )
        target_options.register(interpreter_options_parser, include_platforms=False)

    @classmethod
    def add_extra_arguments(
        cls,
        parser,  # type: ArgumentParser
    ):
        # type: (...) -> None
        subcommands = cls.create_subcommands(
            parser,
            description="Interact with local interpreters via the following subcommands.",
        )
        with subcommands.parser(
            name="inspect",
            help="Inspect local interpreters",
            func=cls._inspect,
            include_verbosity=False,
        ) as inspect_parser:
            cls._add_inspect_arguments(inspect_parser)

    def _inspect(self):
        # type: () -> Result

        interpreter_configuration = target_options.configure_interpreters(self.options)
        try:
            interpreters = interpreter_configuration.resolve_interpreters()
        except (InterpreterNotFound, InterpreterConstraintsNotSatisfied) as e:
            return Error(str(e))

        if self.options.all:
            python_path = (
                interpreter_configuration.python_path.split(":")
                if interpreter_configuration.python_path
                else None
            )
            interpreters.update(PythonInterpreter.all(paths=python_path))
        if not interpreters:
            interpreters.add(PythonInterpreter.get())

        verbose = self.options.verbose or self.options.tags or self.options.markers
        if self.options.indent and not verbose:
            logger.warning(
                "Ignoring --indent={} since --verbose mode is not enabled.".format(
                    self.options.indent
                )
            )
        with self.output(self.options) as out:
            for interpreter in interpreters:
                if verbose:
                    interpreter_info = {"path": interpreter.binary}  # type: Dict[str, Any]
                    if self.options.verbose:
                        interpreter_info.update(
                            version=interpreter.identity.version_str,
                            requirement=str(interpreter.identity.requirement),
                            platform=str(interpreter.platform),
                            venv=interpreter.is_venv,
                        )
                        if interpreter.is_venv:
                            try:
                                interpreter_info[
                                    "base_interpreter"
                                ] = interpreter.resolve_base_interpreter().binary
                            except PythonInterpreter.BaseInterpreterResolutionError as e:
                                logger.warning(
                                    "Failed to determine base interpreter for venv interpreter "
                                    "{interpreter}: {err}".format(
                                        interpreter=interpreter.binary, err=e
                                    )
                                )
                            interpreter_info[
                                "base_interpreter"
                            ] = interpreter.resolve_base_interpreter().binary
                    if self.options.tags:
                        interpreter_info[
                            "compatible_tags"
                        ] = interpreter.identity.supported_tags.to_string_list()
                    if self.options.markers:
                        interpreter_info[
                            "marker_environment"
                        ] = interpreter.identity.env_markers.as_dict()
                    self.dump_json(self.options, interpreter_info, out)
                else:
                    out.write(interpreter.binary)
                out.write("\n")

        return Ok()
