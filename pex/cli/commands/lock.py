# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import ArgumentParser, _ActionsContainer
from collections import defaultdict

from pex.cli.command import BuildTimeCommand
from pex.cli.commands import lockfile
from pex.cli.commands.lockfile import Lockfile, create, json_codec
from pex.commands.command import Error, JsonMixin, Ok, OutputMixin, Result, try_
from pex.common import pluralize
from pex.distribution_target import DistributionTarget
from pex.enum import Enum
from pex.resolve import requirement_options, resolver_options, target_options
from pex.resolve.locked_resolve import LockConfiguration, LockedResolve, LockStyle
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, List, Union


class ExportFormat(Enum["ExportFormat.Value"]):
    class Value(Enum.Value):
        pass

    PIP = Value("pip")
    PEP_665 = Value("pep-665")


class Lock(OutputMixin, JsonMixin, BuildTimeCommand):
    """Operate on PEX lock files."""

    @staticmethod
    def _add_target_options(parser):
        # type: (_ActionsContainer) -> None
        target_options.register(
            parser.add_argument_group(
                title="Target options",
                description=(
                    "Specify which interpreters and platforms resolved distributions must support."
                ),
            )
        )

    @classmethod
    def _create_resolver_options_group(cls, parser):
        # type: (_ActionsContainer) -> _ActionsContainer
        return parser.add_argument_group(
            title="Resolver options",
            description="Configure how third party distributions are resolved.",
        )

    @classmethod
    def _add_resolve_options(cls, parser):
        # type: (_ActionsContainer) -> None
        requirement_options.register(
            parser.add_argument_group(
                title="Requirement options",
                description="Indicate which third party distributions should be resolved",
            )
        )
        cls._add_target_options(parser)
        resolver_options.register(
            cls._create_resolver_options_group(parser),
            include_pex_repository=False,
        )

    @classmethod
    def _add_lockfile_option(cls, parser):
        parser.add_argument(
            "lockfile",
            nargs=1,
            help="The Pex lock file to export",
        )

    @classmethod
    def _add_create_arguments(cls, create_parser):
        # type: (_ActionsContainer) -> None
        create_parser.add_argument(
            "--style",
            default=LockStyle.STRICT,
            choices=LockStyle.values(),
            type=LockStyle.for_value,
            help=(
                "The style of lock to generate. The {strict!r} style is the default and generates "
                "a lock file that contains exactly the distributions that would be used in a local "
                "resolve. If an sdist would be used, the sdist is included, but if a wheel would "
                "be used, an accompanying sdist will not be included. The {sources} style includes "
                "locks containing wheels and the associated sdists when available.".format(
                    strict=LockStyle.STRICT, sources=LockStyle.SOURCES
                )
            ),
        )
        cls.add_output_option(create_parser, entity="lock")
        cls.add_json_options(create_parser, entity="lock", include_switch=False)
        cls._add_resolve_options(create_parser)

    @classmethod
    def _add_export_arguments(cls, export_parser):
        # type: (_ActionsContainer) -> None
        export_parser.add_argument(
            "--format",
            default=ExportFormat.PIP,
            choices=ExportFormat.values(),
            type=ExportFormat.for_value,
            help=(
                "The format to export the lock to. Currently only the {pip!r} requirements file "
                "format using `--hash` is supported.".format(pip=ExportFormat.PIP)
            ),
        )
        cls._add_lockfile_option(export_parser)
        cls.add_output_option(export_parser, entity="lock")
        cls._add_target_options(export_parser)

    @classmethod
    def add_extra_arguments(
        cls,
        parser,  # type: ArgumentParser
    ):
        # type: (...) -> None
        subcommands = cls.create_subcommands(
            parser,
            description="PEX lock files can be operated on using any of the following subcommands.",
        )
        with subcommands.parser(
            name="create", help="Create a lock file.", func=cls._create
        ) as create_parser:
            cls._add_create_arguments(create_parser)
        with subcommands.parser(
            name="export", help="Export a Pex lock file in a different format.", func=cls._export
        ) as export_parser:
            cls._add_export_arguments(export_parser)

    def _create(self):
        # type: () -> Result
        lock_configuration = LockConfiguration(style=self.options.style)
        requirement_configuration = requirement_options.configure(self.options)
        target_configuration = target_options.configure(self.options)
        pip_configuration = resolver_options.create_pip_configuration(self.options)
        lock_file = try_(
            create(
                lock_configuration=lock_configuration,
                requirement_configuration=requirement_configuration,
                target_configuration=target_configuration,
                pip_configuration=pip_configuration,
            )
        )
        with self.output(self.options) as output:
            self.dump_json(self.options, json_codec.as_json_data(lock_file), output, sort_keys=True)
        return Ok()

    @staticmethod
    def _load_lockfile(lockfile_path):
        # type: (str) -> Union[Lockfile, Error]
        try:
            return lockfile.load(lockfile_path)
        except lockfile.ParseError as e:
            return Error(str(e))

    def _export(self):
        # type: () -> Result
        if self.options.format != ExportFormat.PIP:
            return Error(
                "Only the {pip!r} lock format is supported currently.".format(pip=ExportFormat.PIP)
            )

        lockfile_path = self.options.lockfile[0]
        lock_file = try_(self._load_lockfile(lockfile_path=lockfile_path))

        target_configuration = target_options.configure(self.options)
        targets = target_configuration.unique_targets()

        selected_locks = defaultdict(
            list
        )  # type: DefaultDict[LockedResolve, List[DistributionTarget]]
        with TRACER.timed("Selecting locks for {count} targets".format(count=len(targets))):
            for target, locked_resolve in lock_file.select(targets):
                selected_locks[locked_resolve].append(target)

        if len(selected_locks) == 1:
            locked_resolve, _ = selected_locks.popitem()
            with self.output(self.options) as output:
                locked_resolve.emit_requirements(output)
            return Ok()

        locks = lock_file.locked_resolves
        if not selected_locks:
            return Error(
                "Of the {count} {locks} stored in {lockfile}, none were applicable for the "
                "selected targets:\n"
                "{targets}".format(
                    count=len(locks),
                    locks=pluralize(locks, "lock"),
                    lockfile=lockfile_path,
                    targets="\n".join(
                        "{index}.) {target}".format(index=index, target=target)
                        for index, target in enumerate(targets, start=1)
                    ),
                )
            )

        return Error(
            "Only a single lock can be exported in the {pip!r} format.\n"
            "There {were} {count} {locks} stored in {lockfile} that were applicable for the "
            "selected targets:\n"
            "{targets}".format(
                were="was" if len(locks) == 1 else "were",
                count=len(locks),
                locks=pluralize(locks, "lock"),
                lockfile=lockfile_path,
                pip=ExportFormat.PIP,
                targets="\n".join(
                    "{index}.) {platform}: {targets}".format(
                        index=index, platform=lock.platform_tag, targets=targets
                    )
                    for index, (lock, targets) in enumerate(selected_locks.items(), start=1)
                ),
            )
        )
