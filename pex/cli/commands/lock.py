# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import sys
from argparse import Action, ArgumentError, ArgumentParser, ArgumentTypeError, _ActionsContainer
from collections import defaultdict

from pex.argparse import HandleBoolAction
from pex.cli.command import BuildTimeCommand
from pex.commands.command import JsonMixin, OutputMixin
from pex.common import pluralize
from pex.dist_metadata import Requirement, RequirementParseError
from pex.enum import Enum
from pex.orderedset import OrderedSet
from pex.resolve import requirement_options, resolver_options, target_options
from pex.resolve.locked_resolve import LockConfiguration, LockedResolve, LockStyle
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.operations import create
from pex.resolve.lockfile.updater import LockUpdater, ResolveUpdateRequest
from pex.resolve.resolver_options import parse_lockfile
from pex.resolve.target_configuration import InterpreterConstraintsNotSatisfied
from pex.result import Error, Ok, Result, try_
from pex.sorted_tuple import SortedTuple
from pex.targets import Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.version import __version__

if TYPE_CHECKING:
    from typing import IO, DefaultDict, List, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class ExportFormat(Enum["ExportFormat.Value"]):
    class Value(Enum.Value):
        pass

    PIP = Value("pip")
    PEP_665 = Value("pep-665")


class DryRunStyle(Enum["DryRunStyle.Value"]):
    class Value(Enum.Value):
        pass

    DISPLAY = Value("display")
    CHECK = Value("check")


class HandleDryRunAction(Action):
    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = "?"
        super(HandleDryRunAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        if option_str.startswith("--no-"):
            if value:
                raise ArgumentError(
                    None,
                    "The {option} option does not take a value; given: {value!r}".format(
                        option=option_str, value=value
                    ),
                )
            dry_run_style = None
        elif value:
            try:
                dry_run_style = DryRunStyle.for_value(value)
            except ValueError:
                raise ArgumentTypeError(
                    "Invalid value for {option}: {value!r}. Either pass no value for {default!r} "
                    "or one of: {choices}".format(
                        option=option_str,
                        value=value,
                        default=DryRunStyle.DISPLAY,
                        choices=", ".join(map(repr, DryRunStyle.values())),
                    )
                )
        else:
            dry_run_style = DryRunStyle.DISPLAY
        setattr(namespace, self.dest, dry_run_style)


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
            include_lock=False,
        )

    @classmethod
    def _add_lockfile_option(cls, parser, verb):
        # type: (_ActionsContainer, str) -> None
        parser.add_argument(
            "lockfile",
            nargs=1,
            help="The Pex lock file to {verb}".format(verb=verb),
        )

    @classmethod
    def _add_lock_options(cls, parser):
        # type: (_ActionsContainer) -> None
        resolver_options.register_lock_options(parser)

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
                "PEX build. If an sdist would be used, the sdist is included, but if a wheel would "
                "be used, an accompanying sdist will not be included. The {sources!r} style "
                "includes locks containing both wheels and the associated sdists when available. "
                "The {universal!r} style generates a universal lock for all possible target "
                "interpreters and platforms, although the scope can be constrained via one or more "
                "--interpreter-constraint. Of the three lock styles, only {strict!r} can give you "
                "full confidence in the lock since it includes exactly the artifacts that are "
                "included in the local PEX you'll build to test the lock result with before "
                "checking in the lock. With the other two styles you lock un-vetted artifacts in "
                "addition to the {strict!r} ones; so, even though you can be sure to reproducibly "
                "resolve those same un-vetted artifacts in the future, they're still un-vetted and "
                "could be innocently or maliciously different from the {strict!r} artifacts you "
                "can locally vet before committing the lock to version control. The effects of the "
                "differences could range from failing a resolve using the lock when the un-vetted "
                "artifacts have different dependencies from their sibling artifacts, to your "
                "application crashing due to different code in the sibling artifacts to being "
                "compromised by differing code in the sibling artifacts. So, although the more "
                "permissive lock styles will allow the lock to work on a wider range of machines /"
                "are apparently more convenient, the convenience comes with a potential price and "
                "using these styles should be considered carefully.".format(
                    strict=LockStyle.STRICT,
                    sources=LockStyle.SOURCES,
                    universal=LockStyle.UNIVERSAL,
                )
            ),
        )
        cls._add_lock_options(create_parser)
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
        cls._add_lockfile_option(export_parser, verb="export")
        cls._add_lock_options(export_parser)
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
            help=(
                "Just attempt to update these projects in the lock, leaving all others unchanged. "
                "If the projects aren't already in the lock, attempt to add them as top-level"
                "requirements leaving all others unchanged."
            ),
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
            action=HandleDryRunAction,
            help=(
                "Don't update the lock file; just report what updates would be made. By default, "
                "the report is to STDOUT and the exit code is zero. If a value of {check!r} is "
                "passed, the report is to STDERR and the exit code is non-zero.".format(
                    check=DryRunStyle.CHECK
                )
            ),
        )
        cls._add_lockfile_option(update_parser, verb="create")
        cls._add_lock_options(update_parser)
        cls.add_json_options(update_parser, entity="lock", include_switch=False)
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
        target_configuration = target_options.configure(self.options)
        if self.options.style == LockStyle.UNIVERSAL:
            if target_configuration.pythons or target_configuration.platforms:
                return Error(
                    "When creating a {universal} lock, the interpreters the resulting lock applies "
                    "to can only be constrained via --interpreter-constraint. There {were} "
                    "{num_pythons} --python and {num_platforms} --platform specified.".format(
                        universal=LockStyle.UNIVERSAL.value,
                        were="were" if len(target_configuration.pythons) > 1 else "was",
                        num_pythons=len(target_configuration.pythons),
                        num_platforms=len(target_configuration.platforms),
                    )
                )
            lock_configuration = LockConfiguration(
                style=LockStyle.UNIVERSAL,
                requires_python=tuple(
                    str(interpreter_constraint.specifier)
                    for interpreter_constraint in target_configuration.interpreter_constraints
                ),
            )
            if target_configuration.interpreter_constraints:
                try:
                    interpreter = next(
                        target_configuration.interpreter_configuration.iter_interpreters()
                    )
                except InterpreterConstraintsNotSatisfied as e:
                    return Error(
                        "When creating a universal lock with an --interpreter-constraint, an "
                        "interpreter matching the constraint must be found on the local system but "
                        "none was: {err}".format(err=e)
                    )
                targets = Targets(interpreters=(interpreter,))
            else:
                targets = Targets()
        else:
            lock_configuration = LockConfiguration(style=self.options.style)
            targets = target_configuration.resolve_targets()

        requirement_configuration = requirement_options.configure(self.options)
        pip_configuration = resolver_options.create_pip_configuration(self.options)
        self._dump_lockfile(
            try_(
                create(
                    lock_configuration=lock_configuration,
                    requirement_configuration=requirement_configuration,
                    targets=targets,
                    pip_configuration=pip_configuration,
                )
            )
        )
        return Ok()

    def _load_lockfile(self):
        # type: () -> Tuple[str, Lockfile]
        lock_file_path = self.options.lockfile[0]
        return lock_file_path, try_(parse_lockfile(self.options, lock_file_path=lock_file_path))

    def _dump_lockfile(
        self,
        lock_file,  # type: Lockfile
        output=None,  # type: Optional[IO]
    ):
        # type: (...) -> None
        path_mappings = resolver_options.get_path_mappings(self.options)

        def dump_with_terminating_newline(out):
            # json.dump() does not write the newline terminating the last line, but some
            # JSON linters, and line-based tools in general, expect it, and since these
            # files are intended to be checked in to repos that may enforce this, we oblige.
            self.dump_json(
                self.options,
                json_codec.as_json_data(lockfile=lock_file, path_mappings=path_mappings),
                out=out,
                sort_keys=True,
            )
            out.write("\n")

        if output:
            dump_with_terminating_newline(out=output)
        else:
            with self.output(self.options) as output:
                dump_with_terminating_newline(out=output)

    def _export(self):
        # type: () -> Result
        if self.options.format != ExportFormat.PIP:
            return Error(
                "Only the {pip!r} lock format is supported currently.".format(pip=ExportFormat.PIP)
            )

        lockfile_path, lock_file = self._load_lockfile()

        targets = target_options.configure(self.options).resolve_targets().unique_targets()

        selected_locks = defaultdict(list)  # type: DefaultDict[LockedResolve, List[Target]]
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
        try:
            update_requirements = tuple(
                Requirement.parse(project) for project in self.options.projects
            )
        except RequirementParseError as e:
            return Error("Failed to parse project requirement to update: {err}".format(err=e))

        lock_file_path, lock_file = self._load_lockfile()
        lock_updater = LockUpdater.create(
            lock_file=lock_file,
            repos_configuration=resolver_options.create_repos_configuration(self.options),
            network_configuration=resolver_options.create_network_configuration(self.options),
            max_jobs=resolver_options.get_max_jobs_value(self.options),
        )

        targets = (
            Targets()
            if lock_file.style == LockStyle.UNIVERSAL
            else target_options.configure(self.options).resolve_targets()
        )
        update_requests = [
            ResolveUpdateRequest(target=target, locked_resolve=locked_resolve)
            for target, locked_resolve in lock_file.select(targets.unique_targets())
        ]
        if self.options.strict:
            missing_updates = set(lock_file.locked_resolves) - {
                update_request.locked_resolve for update_request in update_requests
            }
            if missing_updates:
                return Error(
                    "This lock update is --strict but the following platforms present in "
                    "{lock_file} were not found on the local machine:\n"
                    "{missing_platforms}\n"
                    "You might be able to correct this by adjusting target options like "
                    "--python-path or else by relaxing the update to be --non-strict.".format(
                        lock_file=lock_file_path,
                        missing_platforms="\n".join(
                            sorted(
                                "+ {platform}".format(platform=locked_resolve.platform_tag)
                                for locked_resolve in missing_updates
                            )
                        ),
                    )
                )

        if not update_requests:
            return Ok(
                "No lock update was performed.\n"
                "The following platforms present in {lock_file} were not found on the local "
                "machine:\n"
                "{missing_platforms}\n"
                "You might still be able to update the lock by adjusting target options like "
                "--python-path.".format(
                    lock_file=lock_file_path,
                    missing_platforms="\n".join(
                        sorted(
                            "+ {platform}".format(platform=locked_resolve.platform_tag)
                            for locked_resolve in lock_file.locked_resolves
                        )
                    ),
                )
            )

        lock_update = try_(
            lock_updater.update(
                update_requests=update_requests,
                updates=update_requirements,
                assume_manylinux=targets.assume_manylinux,
            )
        )

        constraints_by_project_name = {
            constraint.project_name: constraint for constraint in lock_file.constraints
        }
        dry_run = self.options.dry_run
        output = sys.stdout if dry_run is DryRunStyle.DISPLAY else sys.stderr
        version_updates = []
        for resolve_update in lock_update.resolves:
            platform = resolve_update.updated_resolve.platform_tag or "universal"
            for project_name, version_update in resolve_update.updates.items():
                if version_update:
                    version_updates.append(version_update)
                    if version_update.original:
                        print(
                            "{lead_in} {project_name} from {original_version} to {updated_version} "
                            "in lock generated by {platform}.".format(
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
                            "{lead_in} {project_name} {updated_version} to lock generated by "
                            "{platform}.".format(
                                lead_in="Would add" if dry_run else "Added",
                                project_name=project_name,
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
        if not version_updates:
            return Ok()

        if dry_run:
            return Error() if dry_run is DryRunStyle.CHECK else Ok()

        original_locked_project_names = {
            locked_requirement.pin.project_name
            for locked_resolve in lock_file.locked_resolves
            for locked_requirement in locked_resolve.locked_requirements
        }
        new_requirements = OrderedSet(
            update
            for update in update_requirements
            if update.project_name not in original_locked_project_names
        )
        constraints_by_project_name.update(
            (constraint.project_name, constraint) for constraint in update_requirements
        )
        for requirement in new_requirements:
            constraints_by_project_name.pop(requirement.project_name, None)
        requirements = OrderedSet(lock_file.requirements)
        requirements.update(new_requirements)

        with open(lock_file_path, "w") as fp:
            self._dump_lockfile(
                lock_file=attr.evolve(
                    lock_file,
                    pex_version=__version__,
                    requirements=SortedTuple(requirements, key=str),
                    constraints=SortedTuple(constraints_by_project_name.values(), key=str),
                    locked_resolves=SortedTuple(
                        resolve_update.updated_resolve for resolve_update in lock_update.resolves
                    ),
                ),
                output=fp,
            )
        return Ok()
