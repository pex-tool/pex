# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from argparse import ArgumentParser, _ActionsContainer, _SubParsersAction

from pex import resolver
from pex.cli.command import BuildTimeCommand
from pex.commands.command import Ok, OutputMixin, Result
from pex.resolve import requirement_options, resolver_options, target_options
from pex.resolve.locked_resolve import LockConfiguration, LockStyle
from pex.variables import ENV


class Lock(OutputMixin, BuildTimeCommand):
    """Operate on PEX lock files."""

    @staticmethod
    def _add_resolve_options(parser):
        # type: (_ActionsContainer) -> None
        requirement_options.register(
            parser.add_argument_group(
                title="Requirement options",
                description="Indicate which third party distributions should be resolved",
            )
        )
        target_options.register(
            parser.add_argument_group(
                title="Target options",
                description=(
                    "Specify which interpreters and platforms resolved distributions must support."
                ),
            )
        )
        resolver_options.register(
            parser.add_argument_group(
                title="Resolver options",
                description="Configure how third party distributions are resolved.",
            ),
            include_pex_repository=False,
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
        cls._add_resolve_options(create_parser)

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

    def _create(self):
        # type: () -> Result
        requirement_configuration = requirement_options.configure(self.options)
        pip_configuration = resolver_options.create_pip_configuration(self.options)
        target_configuration = target_options.configure(self.options)
        lock_configuration = LockConfiguration(style=self.options.style)
        downloaded = resolver.download(
            requirements=requirement_configuration.requirements,
            requirement_files=requirement_configuration.requirement_files,
            constraint_files=requirement_configuration.constraint_files,
            allow_prereleases=pip_configuration.allow_prereleases,
            transitive=pip_configuration.transitive,
            interpreters=target_configuration.interpreters,
            platforms=target_configuration.platforms,
            indexes=pip_configuration.indexes,
            find_links=pip_configuration.find_links,
            resolver_version=pip_configuration.resolver_version,
            network_configuration=pip_configuration.network_configuration,
            cache=ENV.PEX_ROOT,
            build=pip_configuration.allow_builds,
            use_wheel=pip_configuration.allow_wheels,
            assume_manylinux=target_configuration.assume_manylinux,
            max_parallel_jobs=pip_configuration.max_jobs,
            lock_configuration=lock_configuration,
            # We're just out for the lock data and not the distribution files downloaded to produce
            # that data.
            dest=None,
        )
        with self.output(self.options) as output:
            for lock in downloaded.locks:
                lock.emit_requirements(output)
        return Ok()
