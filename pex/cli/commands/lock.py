# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import sys
from argparse import ArgumentParser, _ActionsContainer
from collections import OrderedDict, defaultdict

from pex.argparse import HandleBoolAction
from pex.cli.command import BuildTimeCommand
from pex.cli.commands import lockfile
from pex.cli.commands.lockfile import Lockfile, create, json_codec
from pex.cli.commands.lockfile.updater import LockUpdater, VersionUpdate
from pex.commands.command import Error, JsonMixin, Ok, OutputMixin, Result, catch, try_
from pex.common import pluralize
from pex.distribution_target import DistributionTarget
from pex.enum import Enum
from pex.pep_503 import ProjectName
from pex.resolve import requirement_options, resolver_options, target_options
from pex.resolve.locked_resolve import LockConfiguration, LockedResolve, LockStyle
from pex.resolve.resolver_configuration import PipConfiguration
from pex.resolve.target_configuration import TargetConfiguration
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging import tags
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.version import __version__

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import DefaultDict, List, Mapping, Optional, Union
else:
    from pex.third_party import attr


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
    def _add_update_arguments(cls, update_parser):
        # type: (_ActionsContainer) -> None
        update_parser.add_argument(
            "-p",
            "--project",
            dest="projects",
            action="append",
            default=[],
            type=str,
            help="Just attempt to update these projects in the lock, leaving all others unchanged.",
        )
        update_parser.add_argument(
            "--strict",
            "--no-strict",
            "--non-strict",
            action=HandleBoolAction,
            default=True,
            type=bool,
            help=(
                "Require all target platforms in the lock be updated at once. If any target "
                "platform in the lock file does not have a representative local interpreter to "
                "execute the lock update with, the update will fail."
            ),
        )
        update_parser.add_argument(
            "-n",
            "--dry-run",
            "--no-dry-run",
            action=HandleBoolAction,
            default=False,
            type=bool,
            help="Don't update the lock file; just report what updates would be made.",
        )
        cls._add_lockfile_option(update_parser)
        cls._add_target_options(update_parser)
        resolver_options_parser = cls._create_resolver_options_group(update_parser)
        resolver_options.register_repos_options(resolver_options_parser)
        resolver_options.register_network_options(resolver_options_parser)
        resolver_options.register_max_jobs_option(resolver_options_parser)

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
        with subcommands.parser(
            name="update", help="Update a Pex lock file.", func=cls._update
        ) as update_parser:
            cls._add_update_arguments(update_parser)

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

    def _update(self):
        # type: () -> Result
        lockfile_path = self.options.lockfile[0]
        lock_file = try_(self._load_lockfile(lockfile_path=lockfile_path))

        target_configuration = target_options.configure(self.options)
        targets_by_platform_tag = OrderedDict(
            (target.get_supported_tags()[0], target)
            for target in target_configuration.unique_targets()
        )  # type: OrderedDict[tags.Tag, DistributionTarget]

        if self.options.strict:
            required_platforms = {
                locked_resolve.platform_tag for locked_resolve in lock_file.locked_resolves
            }
            platforms_in_hand = required_platforms.intersection(targets_by_platform_tag.keys())
            if platforms_in_hand != required_platforms:
                return Error(
                    "This lock update is --strict but the following platforms present in "
                    "{lock_file} were not found on the local machine:\n"
                    "{missing_platforms}\n"
                    "You might be able to correct this by adjusting target options like "
                    "--python-path or else by relaxing the update to be --non-strict.".format(
                        lock_file=lockfile_path,
                        missing_platforms="\n".join(
                            sorted(
                                "+ {platform}".format(platform=platform)
                                for platform in required_platforms - platforms_in_hand
                            )
                        ),
                    )
                )

        targets_to_update = OrderedDict()  # type: OrderedDict[DistributionTarget, LockedResolve]
        for locked_resolve in lock_file.locked_resolves:
            target = targets_by_platform_tag.get(locked_resolve.platform_tag)
            if target:
                targets_to_update[target] = locked_resolve

        if not targets_to_update:
            return Ok()

        lock_configuration = LockConfiguration(style=lock_file.style)
        repos_configuration = resolver_options.create_repos_configuration(self.options)
        network_configuration = resolver_options.create_network_configuration(self.options)
        max_jobs = resolver_options.get_max_jobs_value(self.options)
        pip_configuration = PipConfiguration(
            resolver_version=lock_file.resolver_version,
            allow_prereleases=lock_file.allow_prereleases,
            allow_wheels=lock_file.allow_wheels,
            allow_builds=lock_file.allow_builds,
            transitive=lock_file.transitive,
            repos_configuration=repos_configuration,
            network_configuration=network_configuration,
            max_jobs=max_jobs,
        )

        lock_updater = LockUpdater.create(
            requirements=lock_file.requirements,
            constraints=lock_file.constraints,
            updates=self.options.projects,
            lock_configuration=lock_configuration,
            pip_configuration=pip_configuration,
        )

        error_by_target = OrderedDict()  # type: OrderedDict[DistributionTarget, Error]
        lock_updates_by_platform = (
            OrderedDict()
        )  # type: OrderedDict[tags.Tag, Mapping[ProjectName, Optional[VersionUpdate]]]
        locked_resolve_by_platform = OrderedDict(
            (locked_resolve.platform_tag, locked_resolve)
            for locked_resolve in lock_file.locked_resolves
        )  # type: OrderedDict[tags.Tag, LockedResolve]

        # TODO(John Sirois): Consider parallelizing this. The underlying Jobs are down a few layers;
        #  so this will likely require using multiprocessing.
        dry_run = self.options.dry_run
        for target, locked_resolve in targets_to_update.items():
            target_configuration = TargetConfiguration(
                interpreters=(target.get_interpreter(),) if target.is_interpreter else (),
                platforms=(target.get_platform()[0],) if target.is_platform else (),
                assume_manylinux=target_configuration.assume_manylinux,
            )
            result = catch(
                lock_updater.update_resolve,
                locked_resolve=locked_resolve,
                target_configuration=target_configuration,
            )
            if isinstance(result, Error):
                error_by_target[target] = result
            else:
                platform = target.get_supported_tags()[0]
                lock_updates_by_platform[platform] = result.updates
                locked_resolve_by_platform[platform] = result.updated_resolve

        if error_by_target:
            return Error(
                "Encountered {count} {errors} updating {lockfile_path}:\n{error_details}".format(
                    count=len(error_by_target),
                    errors=pluralize(error_by_target, "error"),
                    lockfile_path=lockfile_path,
                    error_details="\n".join(
                        "{index}.) {platform}: {error}".format(
                            index=index, platform=target.get_supported_tags()[0], error=error
                        )
                        for index, (target, error) in enumerate(error_by_target.items(), start=1)
                    ),
                ),
            )

        output = sys.stdout if dry_run else sys.stderr
        for platform, lock_updates in lock_updates_by_platform.items():
            for project_name, version_update in lock_updates.items():
                if version_update:
                    print(
                        "{lead_in} {project_name} from {original_version} to {updated_version} in "
                        "lock generated by {platform}.".format(
                            lead_in="Would update" if dry_run else "Updated",
                            project_name=project_name,
                            original_version=version_update.original,
                            updated_version=version_update.updated,
                            platform=platform,
                        ),
                        file=output,
                    )
                else:
                    print(
                        "There {tense} no updates for {project_name} in lock generated by "
                        "{platform}.".format(
                            tense="would be" if dry_run else "were",
                            project_name=project_name,
                            platform=platform,
                        ),
                        file=output,
                    )
        if not dry_run:
            lockfile.store(
                attr.evolve(
                    lock_file,
                    pex_version=__version__,
                    locked_resolves=SortedTuple(locked_resolve_by_platform.values()),
                ),
                lockfile_path,
            )
        return Ok()
