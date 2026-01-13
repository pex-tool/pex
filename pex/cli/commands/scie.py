# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
from argparse import ArgumentParser

from pex import scie, specifier_sets
from pex.cli.command import BuildTimeCommand
from pex.commands.command import OutputMixin
from pex.fetcher import URLFetcher
from pex.interpreter_constraints import InterpreterConstraints
from pex.pep_440 import Version
from pex.pex_info import PexInfo
from pex.resolve import resolver_options, target_options
from pex.resolve.target_configuration import TargetConfiguration
from pex.result import Error, Ok, Result, catch, try_
from pex.scie import build as build_scies
from pex.targets import Targets
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _narrow_interpreter_constraints(
    pex_interpreter_constraints,  # type: InterpreterConstraints
    user_interpreter_constraints,  # type: InterpreterConstraints
):
    # type: (...) -> Union[InterpreterConstraints, Error]

    if not pex_interpreter_constraints:
        return user_interpreter_constraints

    if not user_interpreter_constraints:
        return pex_interpreter_constraints

    for user_interpreter_constraint in user_interpreter_constraints:
        if not any(
            (
                (
                    not pex_interpreter_constraint.implementation
                    or (
                        user_interpreter_constraint.implementation
                        and pex_interpreter_constraint.implementation.includes(
                            user_interpreter_constraint.implementation
                        )
                    )
                )
                and specifier_sets.includes(
                    pex_interpreter_constraint.specifier,
                    user_interpreter_constraint.specifier,
                )
            )
            for pex_interpreter_constraint in pex_interpreter_constraints
        ):
            return Error(
                "The PEX has interpreter constraints of {pex_interpreter_constraints} and the "
                "user-supplied interpreter constraints of {user_interpreter_constraints} do not "
                "form a subset of those.".format(
                    pex_interpreter_constraints=" or ".join(map(str, pex_interpreter_constraints)),
                    user_interpreter_constraints=" or ".join(
                        map(str, user_interpreter_constraints)
                    ),
                )
            )
    return user_interpreter_constraints


def _resolve_targets(
    pex_interpreter_constraints,  # type: InterpreterConstraints
    target_configuration,  # type: TargetConfiguration
):
    # type: (...) -> Union[Targets, Error]

    interpreter_constraints_or_error = _narrow_interpreter_constraints(
        pex_interpreter_constraints=pex_interpreter_constraints,
        user_interpreter_constraints=target_configuration.interpreter_constraints,
    )
    if isinstance(interpreter_constraints_or_error, Error):
        return interpreter_constraints_or_error

    if interpreter_constraints_or_error != target_configuration.interpreter_constraints:
        target_configuration = attr.evolve(
            target_configuration,
            interpreter_configuration=attr.evolve(
                target_configuration.interpreter_configuration,
                interpreter_constraints=interpreter_constraints_or_error,
            ),
        )
    return target_configuration.resolve_targets()


class Scie(OutputMixin, BuildTimeCommand):
    """Manipulate scies."""

    @classmethod
    def add_extra_arguments(cls, parser):
        subcommands = cls.create_subcommands(
            parser,
            description="Manipulate scies via the following commands.",
        )
        with subcommands.parser(
            name="create",
            help=(
                "Create one or more scies from an existing PEX file."
                "N.B.: The PEX must have been created with Pex v2.1.25 (released on January 21st, "
                "2021) or newer."
            ),
            func=cls._create,
            include_verbosity=False,
        ) as create_parser:
            cls._add_create_arguments(create_parser)

    @classmethod
    def _add_create_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        parser.add_argument(
            "pex",
            nargs=1,
            help="The path of a PEX to create one or more scies from.",
            metavar="PATH",
        )
        cls.add_output_option(parser, "scie information")
        scie.register_options(
            parser.add_argument_group(title="Scie options"),
            style_option_names=("--style", "--scie", "--scie-style"),
        )
        target_options.register(
            parser.add_argument_group(title="Target interpreter options"), include_platforms=True
        )
        resolver_options.register(
            parser.add_argument_group(title="Pip options"),
        )

    def _create(self):
        # type: () -> Result

        scie_options = scie.extract_options(self.options)
        if not scie_options:
            return Error("You must specify `--style {eager,lazy}`.")

        pex_file = self.options.pex[0]
        pex_info_or_error = catch(PexInfo.from_pex, pex_file)
        if isinstance(pex_info_or_error, Error):
            return Error(
                "The path {pex_file} does not appear to be a PEX: {err}".format(
                    pex_file=pex_file, err=pex_info_or_error
                )
            )
        raw_pex_version = pex_info_or_error.build_properties.get("pex_version")
        if raw_pex_version and Version(raw_pex_version) < Version("2.1.25"):
            return Error(
                "Can only create scies from PEXes built by Pex 2.1.25 (which was released on "
                "January 21st, 2021) or newer.\n"
                "The PEX at {pex_file} was built by Pex {pex_version}.".format(
                    pex_file=pex_file, pex_version=raw_pex_version
                )
            )

        resolver_configuration = resolver_options.configure(self.options)
        targets = try_(
            _resolve_targets(
                pex_interpreter_constraints=pex_info_or_error.interpreter_constraints,
                target_configuration=target_options.configure(
                    self.options, pip_configuration=resolver_configuration.pip_configuration
                ),
            )
        )

        scie_configuration = scie_options.create_configuration(targets=targets)
        if not scie_configuration:
            return Error(
                "You selected `{scie_options}`, but none of the selected targets have "
                "compatible interpreters that can be embedded to form a scie:\n{targets}".format(
                    scie_options=scie.render_options(scie_options),
                    targets="\n".join(
                        target.render_description() for target in targets.unique_targets()
                    ),
                )
            )

        url_fetcher = URLFetcher(
            network_configuration=resolver_configuration.network_configuration,
            handle_file_urls=True,
            password_entries=resolver_configuration.repos_configuration.password_entries,
        )
        with self.output(self.options) as out:
            for scie_info in build_scies(
                configuration=scie_configuration,
                pex_file=pex_file,
                url_fetcher=url_fetcher,
            ):
                print(
                    "Saved PEX scie for {python_description} to {scie}".format(
                        python_description=scie_info.interpreter.render_description(),
                        scie=os.path.relpath(scie_info.file),
                    ),
                    file=out,
                )
            if scie_configuration.options.scie_only and os.path.realpath(
                pex_file
            ) != os.path.realpath(scie_info.file):
                os.unlink(pex_file)

        return Ok()
