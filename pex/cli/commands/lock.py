# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import sys
from argparse import Action, ArgumentError, ArgumentParser, ArgumentTypeError, _ActionsContainer
from collections import OrderedDict
from operator import attrgetter

from pex import pex_warnings
from pex.argparse import HandleBoolAction
from pex.asserts import production_assert
from pex.cli.command import BuildTimeCommand
from pex.commands.command import JsonMixin, OutputMixin
from pex.common import pluralize
from pex.dist_metadata import Requirement, RequirementParseError
from pex.enum import Enum
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve import requirement_options, resolver_options, target_options
from pex.resolve.config import finalize as finalize_resolve_config
from pex.resolve.locked_resolve import LockConfiguration, LockStyle, Resolved, TargetSystem
from pex.resolve.lockfile import json_codec
from pex.resolve.lockfile.create import create
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.subset import subset
from pex.resolve.lockfile.updater import (
    ArtifactUpdate,
    DeleteUpdate,
    FingerprintUpdate,
    LockUpdater,
    ResolveUpdateRequest,
    VersionUpdate,
)
from pex.resolve.path_mappings import PathMappings
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import Fingerprint, Pin
from pex.resolve.resolver_options import parse_lockfile
from pex.resolve.target_configuration import InterpreterConstraintsNotSatisfied, TargetConfiguration
from pex.result import Error, Ok, Result, try_
from pex.sorted_tuple import SortedTuple
from pex.targets import Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.version import __version__

if TYPE_CHECKING:
    from typing import IO, Dict, Iterable, List, Mapping, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class FingerprintMismatch(Enum["FingerprintMismatch.Value"]):
    class Value(Enum.Value):
        pass

    IGNORE = Value("ignore")
    WARN = Value("warn")
    ERROR = Value("error")


class ExportFormat(Enum["ExportFormat.Value"]):
    class Value(Enum.Value):
        pass

    PIP = Value("pip")
    PEP_665 = Value("pep-665")


class ExportSortBy(Enum["ExportSortBy.Value"]):
    class Value(Enum.Value):
        pass

    SPECIFICITY = Value("specificity")
    PROJECT_NAME = Value("project-name")


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
    def _add_lockfile_option(
        cls,
        parser,  # type: _ActionsContainer
        verb,  # type: str
        positional=True,  # type: bool
    ):
        # type: (...) -> None
        if positional:
            parser.add_argument(
                "lockfile",
                nargs=1,
                help="The Pex lock file to {verb}".format(verb=verb),
            )
        else:
            parser.add_argument(
                "--lock",
                required=True,
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
        create_parser.add_argument(
            "--target-system",
            dest="target_systems",
            default=[],
            action="append",
            choices=TargetSystem.values(),
            type=TargetSystem.for_value,
            help=(
                "The target operating systems to generate the lock for. This option applies only "
                "to `--style {universal}` locks and restricts the locked artifacts to those "
                "compatible with the specified target operating systems. By default, {universal!r} "
                "style locks include artifacts for all operating systems.".format(
                    universal=LockStyle.UNIVERSAL,
                )
            ),
        )
        cls._add_lock_options(create_parser)
        cls.add_output_option(create_parser, entity="lock")
        cls.add_json_options(create_parser, entity="lock", include_switch=False)
        cls._add_resolve_options(create_parser)

    @classmethod
    def _add_export_arguments(
        cls,
        export_parser,  # type: _ActionsContainer
        lockfile_option_positional=True,  # type: bool
    ):
        # type: (...) -> None
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
        export_parser.add_argument(
            "--sort-by",
            default=ExportSortBy.SPECIFICITY,
            choices=ExportSortBy.values(),
            type=ExportSortBy.for_value,
            help="How to sort the requirements in the export (if supported).",
        )
        cls._add_lockfile_option(
            export_parser, verb="export", positional=lockfile_option_positional
        )
        cls._add_lock_options(export_parser)
        cls.add_output_option(export_parser, entity="lock")
        cls._add_target_options(export_parser)
        resolver_options_parser = cls._create_resolver_options_group(export_parser)
        resolver_options.register_network_options(resolver_options_parser)

    @classmethod
    def _add_export_subset_arguments(cls, export_subset_parser):
        # type: (_ActionsContainer) -> None
        cls._add_export_arguments(export_subset_parser, lockfile_option_positional=False)
        requirement_options.register(export_subset_parser)

    @classmethod
    def _add_update_arguments(cls, update_parser):
        # type: (_ActionsContainer) -> None
        update_parser.add_argument(
            "-p",
            "--project",
            "--update-project",
            dest="update_projects",
            action="append",
            default=[],
            type=str,
            help=(
                "Attempt to update these projects in the lock, leaving all others unchanged. "
                "If the projects aren't already in the lock, attempt to add them as top-level "
                "requirements leaving all others unchanged. If a project is already in the lock "
                "and is specified by a top-level requirement, the allowable updates will be "
                "constrained by the original top-level requirement. In other words, for an "
                "original top-level requirement of `requests>=2,<4` you could specify "
                "`-p requests` to pick up new releases in the `>=2,<4` range specified by the "
                "original top-level requirement or you could specify an overlapping range like "
                "`-p 'requests<3.6,!==3.8.2'` to, for example, downgrade away from a newly "
                "identified security vulnerability. If you specify a disjoint requirement like "
                "`-p 'requests>=4'`, the operation will fail. If you really want to replace the "
                "original top-level requirement and have this operation succeed, use the "
                "`--replace-project` option instead. This option is mutually exclusive with "
                "`--pin`."
            ),
        )
        update_parser.add_argument(
            "-R",
            "--replace-project",
            dest="replace_projects",
            action="append",
            default=[],
            type=str,
            help=(
                "Attempt to replace these projects in the lock, leaving all others unchanged. "
                "If the projects aren't already in the lock, attempt to add them as top-level "
                "requirements leaving all others unchanged. If a project is already in the lock "
                "and is specified by a top-level requirement, that top-level requirement will be "
                "replaced. This option is mutually exclusive with `--pin`."
            ),
        )
        update_parser.add_argument(
            "-d",
            "--delete-project",
            dest="delete_projects",
            action="append",
            default=[],
            type=str,
            help=(
                "Attempt to delete these projects from the lock, leaving all others unchanged. "
                "If the projects are not top-level requirements requested in the original lock or "
                "else they are but are transitive dependencies of the remaining top-level "
                "requirements, then no deletion will be performed in order to maintain lock "
                "integrity. This option is mutually exclusive with `--pin`."
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
            "--pin",
            action=HandleBoolAction,
            default=False,
            type=bool,
            help=(
                "When performing the update, pin all projects in the lock to their current "
                "versions. This is useful to pick up newly published wheels for those projects or "
                "else switch repositories from the original ones when used in conjunction with any "
                "of --index, --no-pypi and --find-links. When specifying `--pin`, it is an error "
                "to also specify lock modifications via `-p` / `--project`, "
                "`-R` / `--replace-project` or `-d` / `--delete-project`."
            ),
        )

        update_parser.add_argument(
            "--fingerprint-mismatch",
            default=FingerprintMismatch.ERROR,
            choices=FingerprintMismatch.values(),
            type=FingerprintMismatch.for_value,
            help=(
                "What to do when a lock update would result in at least one artifact fingerprint "
                "changing: {ignore!r} the mismatch and use the new fingerprint, {warn!r} about the "
                "mismatch but use the new fingerprint anyway or {error!r} and refuse to use the "
                "new mismatching fingerprint".format(
                    ignore=FingerprintMismatch.IGNORE,
                    warn=FingerprintMismatch.WARN,
                    error=FingerprintMismatch.ERROR,
                )
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
        cls._add_lockfile_option(update_parser, verb="update")
        cls._add_lock_options(update_parser)
        cls.add_json_options(update_parser, entity="lock", include_switch=False)
        cls._add_target_options(update_parser)
        resolver_options_parser = cls._create_resolver_options_group(update_parser)
        resolver_options.register_repos_options(resolver_options_parser)
        resolver_options.register_network_options(resolver_options_parser)
        resolver_options.register_max_jobs_option(resolver_options_parser)
        resolver_options.register_use_pip_config(resolver_options_parser)

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
            name="export",
            help="Export a Pex lock file for a single targeted environment in a different format.",
            func=cls._export,
        ) as export_parser:
            cls._add_export_arguments(export_parser)
        with subcommands.parser(
            name="export-subset",
            help=(
                "Export a subset of a Pex lock file for a single targeted environment in a "
                "different format."
            ),
            func=cls._export_subset,
        ) as export_subset_parser:
            cls._add_export_subset_arguments(export_subset_parser)
        with subcommands.parser(
            name="update", help="Update a Pex lock file.", func=cls._update
        ) as update_parser:
            cls._add_update_arguments(update_parser)

    def _resolve_targets(
        self,
        action,  # type: str
        style,  # type: LockStyle.Value
        target_configuration=None,  # type: Optional[TargetConfiguration]
    ):
        # type: (...) -> Union[Targets, Error]

        target_config = target_configuration or target_options.configure(self.options)
        if style is not LockStyle.UNIVERSAL:
            return target_config.resolve_targets()

        if target_config.pythons:
            return Error(
                "When {action} a {universal} lock, the interpreters the resulting lock applies "
                "to can only be constrained via --interpreter-constraint. There {were} "
                "{num_pythons} --python specified.".format(
                    action=action,
                    universal=LockStyle.UNIVERSAL.value,
                    were="were" if len(target_config.pythons) > 1 else "was",
                    num_pythons=len(target_config.pythons),
                )
            )

        if not target_config.interpreter_constraints:
            return Targets(
                platforms=target_config.platforms,
                complete_platforms=target_config.complete_platforms,
                assume_manylinux=target_config.assume_manylinux,
            )

        try:
            interpreter = next(target_config.interpreter_configuration.iter_interpreters())
        except InterpreterConstraintsNotSatisfied as e:
            return Error(
                "When {action} a universal lock with an --interpreter-constraint, an "
                "interpreter matching the constraint must be found on the local system but "
                "none was: {err}".format(action=action, err=e)
            )
        return Targets(
            interpreters=(interpreter,),
            platforms=target_config.platforms,
            complete_platforms=target_config.complete_platforms,
            assume_manylinux=target_config.assume_manylinux,
        )

    def _create(self):
        # type: () -> Result
        target_configuration = target_options.configure(self.options)
        if self.options.style == LockStyle.UNIVERSAL:
            lock_configuration = LockConfiguration(
                style=LockStyle.UNIVERSAL,
                requires_python=tuple(
                    str(interpreter_constraint.requires_python)
                    for interpreter_constraint in target_configuration.interpreter_constraints
                ),
                target_systems=tuple(self.options.target_systems),
            )
        elif self.options.target_systems:
            return Error(
                "The --target-system option only applies to --style {universal} locks.".format(
                    universal=LockStyle.UNIVERSAL.value
                )
            )
        else:
            lock_configuration = LockConfiguration(style=self.options.style)

        requirement_configuration = requirement_options.configure(self.options)
        targets = try_(
            self._resolve_targets(
                action="creating",
                style=self.options.style,
                target_configuration=target_configuration,
            )
        )
        pip_configuration = try_(
            finalize_resolve_config(
                resolver_configuration=resolver_options.create_pip_configuration(self.options),
                targets=targets,
                context="lock creation",
            )
        )
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
        lock_file_path = self.options.lock if "lock" in self.options else self.options.lockfile[0]
        return lock_file_path, try_(parse_lockfile(self.options, lock_file_path=lock_file_path))

    def _get_path_mappings(self):
        # type: () -> PathMappings
        return resolver_options.get_path_mappings(self.options)

    def _dump_lockfile(
        self,
        lock_file,  # type: Lockfile
        output=None,  # type: Optional[IO]
    ):
        # type: (...) -> None
        def dump_with_terminating_newline(out):
            # json.dump() does not write the newline terminating the last line, but some
            # JSON linters, and line-based tools in general, expect it, and since these
            # files are intended to be checked in to repos that may enforce this, we oblige.
            self.dump_json(
                self.options,
                json_codec.as_json_data(
                    lockfile=lock_file, path_mappings=self._get_path_mappings()
                ),
                out=out,
                sort_keys=True,
            )
            out.write("\n")

        if output:
            dump_with_terminating_newline(out=output)
        else:
            with self.output(self.options) as output:
                dump_with_terminating_newline(out=output)

    def _export(self, requirement_configuration=RequirementConfiguration()):
        # type: (RequirementConfiguration) -> Result
        if self.options.format != ExportFormat.PIP:
            return Error(
                "Only the {pip!r} lock format is supported currently.".format(pip=ExportFormat.PIP)
            )

        lockfile_path, lock_file = self._load_lockfile()
        targets = target_options.configure(self.options).resolve_targets()
        target = targets.require_unique_target(
            purpose="exporting a lock in the {pip!r} format".format(pip=ExportFormat.PIP)
        )

        network_configuration = resolver_options.create_network_configuration(self.options)
        with TRACER.timed("Selecting locks for {target}".format(target=target)):
            subset_result = try_(
                subset(
                    targets=targets,
                    lock=lock_file,
                    requirement_configuration=requirement_configuration,
                    network_configuration=network_configuration,
                    build_configuration=lock_file.build_configuration(),
                    transitive=lock_file.transitive,
                    include_all_matches=True,
                )
            )

        if len(subset_result.subsets) != 1:
            resolved = Resolved.most_specific(
                resolved_subset.resolved for resolved_subset in subset_result.subsets
            )
            pex_warnings.warn(
                "Only a single lock can be exported in the {pip!r} format.\n"
                "There were {count} locks stored in {lockfile} that were applicable for the "
                "selected target: {target}; so using the most specific lock with platform "
                "{platform}.".format(
                    count=len(subset_result.subsets),
                    lockfile=lock_file.source,
                    pip=ExportFormat.PIP,
                    target=target,
                    platform=resolved.source.platform_tag,
                )
            )
        else:
            resolved = subset_result.subsets[0].resolved

        fingerprints_by_pin = OrderedDict()  # type: OrderedDict[Pin, List[Fingerprint]]
        for downloaded_artifact in resolved.downloadable_artifacts:
            fingerprints_by_pin.setdefault(downloaded_artifact.pin, []).append(
                downloaded_artifact.artifact.fingerprint
            )

        with self.output(self.options) as output:
            pins = fingerprints_by_pin.keys()  # type: Iterable[Pin]
            if self.options.sort_by == ExportSortBy.PROJECT_NAME:
                pins = sorted(pins, key=attrgetter("project_name.normalized"))
            for pin in pins:
                fingerprints = fingerprints_by_pin[pin]
                output.write(
                    "{project_name}=={version} \\\n"
                    "  {hashes}\n".format(
                        project_name=pin.project_name,
                        version=pin.version.raw,
                        hashes=" \\\n  ".join(
                            "--hash={algorithm}:{hash}".format(
                                algorithm=fingerprint.algorithm, hash=fingerprint.hash
                            )
                            for fingerprint in fingerprints
                        ),
                    )
                )
        return Ok()

    def _export_subset(self):
        requirement_configuration = requirement_options.configure(self.options)
        return self._export(requirement_configuration=requirement_configuration)

    def _update(self):
        # type: () -> Result

        if self.options.pin and any(
            (
                self.options.update_projects,
                self.options.replace_projects,
                self.options.delete_projects,
            )
        ):
            return Error(
                "When executing a `--pin`ed update, no `-p` / `--project`, "
                "`-R` / `--replace-project` or `-d` / `--delete-project` modifications are "
                "allowed."
            )

        update_requirements_by_project_name = (
            OrderedDict()
        )  # type: OrderedDict[ProjectName, Requirement]
        for project in self.options.update_projects:
            try:
                requirement = Requirement.parse(project)
            except RequirementParseError as e:
                return Error(
                    "Failed to parse project requirement to update {project!r}: {err}".format(
                        project=project, err=e
                    )
                )
            else:
                update_requirements_by_project_name[requirement.project_name] = requirement

        replace_requirements = []  # type: List[Requirement]
        for project in self.options.replace_projects:
            try:
                replace_requirements.append(Requirement.parse(project))
            except RequirementParseError as e:
                return Error(
                    "Failed to parse replacement project requirement {project!r}: {err}".format(
                        project=project, err=e
                    )
                )

        try:
            delete_projects = tuple(
                ProjectName(project, validated=True) for project in self.options.delete_projects
            )
        except ProjectName.InvalidError as e:
            return Error("Failed to parse project name to delete: {err}".format(err=e))

        lock_file_path, lock_file = self._load_lockfile()
        network_configuration = resolver_options.create_network_configuration(self.options)
        lock_updater = LockUpdater.create(
            lock_file=lock_file,
            repos_configuration=resolver_options.create_repos_configuration(self.options),
            network_configuration=network_configuration,
            max_jobs=resolver_options.get_max_jobs_value(self.options),
            use_pip_config=resolver_options.get_use_pip_config_value(self.options),
        )

        target_configuration = target_options.configure(self.options)
        targets = try_(
            self._resolve_targets(
                action="updating", style=lock_file.style, target_configuration=target_configuration
            )
        )

        lock_updater = attr.evolve(
            lock_updater,
            pip_configuration=try_(
                finalize_resolve_config(
                    resolver_configuration=lock_updater.pip_configuration,
                    targets=targets,
                    context="lock updating",
                    pip_version=lock_file.pip_version,
                )
            ),
        )

        with TRACER.timed("Selecting locks to update"):
            subset_result = try_(
                subset(
                    targets=targets,
                    lock=lock_file,
                    network_configuration=network_configuration,
                    build_configuration=lock_file.build_configuration(),
                    transitive=lock_file.transitive,
                )
            )

        update_requests = [
            ResolveUpdateRequest(
                target=resolved_subset.target, locked_resolve=resolved_subset.resolved.source
            )
            for resolved_subset in subset_result.subsets
        ]
        if self.options.strict and lock_file.style is not LockStyle.UNIVERSAL:
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
                updates=update_requirements_by_project_name.values(),
                replacements=replace_requirements,
                deletes=delete_projects,
                pin=self.options.pin,
            )
        )

        original_requirements_by_project_name = {
            requirement.project_name: requirement for requirement in lock_file.requirements
        }
        requirements_by_project_name = {
            requirement.project_name: requirement for requirement in lock_update.requirements
        }

        original_constraints_by_project_name = {
            constraint.project_name: constraint for constraint in lock_file.constraints
        }
        constraints_by_project_name = original_constraints_by_project_name.copy()

        dry_run = self.options.dry_run
        path_mappings = self._get_path_mappings()
        output = sys.stdout if dry_run is DryRunStyle.DISPLAY else sys.stderr
        updates = []
        warnings = []  # type: List[str]
        for resolve_update in lock_update.resolves:
            platform = resolve_update.updated_resolve.platform_tag or "universal"
            if not resolve_update.updates:
                print(
                    "No updates for lock generated by {platform}.".format(platform=platform),
                    file=output,
                )
                continue

            print(
                "Updates for lock generated by {platform}:".format(platform=platform), file=output
            )
            fingerprint_updates = {}  # type: Dict[ProjectName, Version]
            for project_name, update in resolve_update.updates.items():
                if not update:
                    print(
                        "  There {tense} no updates for {project_name}".format(
                            tense="would be" if dry_run else "were",
                            project_name=project_name,
                        ),
                        file=output,
                    )
                    continue

                updates.append(update)
                if isinstance(update, DeleteUpdate):
                    print(
                        "  {lead_in} {project_name} {deleted_version}".format(
                            lead_in="Would delete" if dry_run else "Deleted",
                            project_name=project_name,
                            deleted_version=update.version,
                        ),
                        file=output,
                    )
                    production_assert(
                        project_name not in requirements_by_project_name,
                        "Deletes should have been unconditionally removed from requirements "
                        "earlier. Found deleted project {project_name} in updated requirements:\n"
                        "{requirements}".format(
                            project_name=project_name,
                            requirements="\n".join(map(str, requirements_by_project_name.values())),
                        ),
                    )
                    constraints_by_project_name.pop(project_name, None)
                elif isinstance(update, VersionUpdate):
                    update_req = update_requirements_by_project_name.get(project_name)
                    if update.original:
                        print(
                            "  {lead_in} {project_name} from {original_version} to "
                            "{updated_version}".format(
                                lead_in="Would update" if dry_run else "Updated",
                                project_name=project_name,
                                original_version=update.original,
                                updated_version=update.updated,
                            ),
                            file=output,
                        )
                        # Only update the constraint if it is truly a constraint. If it's just the
                        # project name with no specifier, markers, etc., then it was just used to
                        # grab the latest version in the range already constrained by an existing
                        # requirement or constraint.
                        if update_req and str(update_req) != update_req.name:
                            constraints_by_project_name[project_name] = update_req
                    else:
                        print(
                            "  {lead_in} {project_name} {updated_version}".format(
                                lead_in="Would add" if dry_run else "Added",
                                project_name=project_name,
                                updated_version=update.updated,
                            ),
                            file=output,
                        )
                        if update_req:
                            requirements_by_project_name[project_name] = update_req
                else:
                    message_lines = [
                        "  {lead_in} {project_name} {version} artifacts:".format(
                            lead_in="Would update" if dry_run else "Updated",
                            project_name=project_name,
                            version=update.version,
                        )
                    ]
                    if update.added:
                        message_lines.extend(
                            "    + {added}".format(
                                added=path_mappings.maybe_canonicalize(artifact.url.download_url)
                            )
                            for artifact in update.added
                        )
                    if update.updated:
                        if any(
                            isinstance(change, (FingerprintUpdate, ArtifactUpdate))
                            for change in update.updated
                        ):
                            fingerprint_updates[project_name] = update.version
                        message_lines.extend(
                            "    {changed}".format(
                                changed=path_mappings.maybe_canonicalize(change.render_update())
                            )
                            for change in update.updated
                        )
                    if update.removed:
                        message_lines.extend(
                            "    - {removed}".format(
                                removed=path_mappings.maybe_canonicalize(artifact.url.download_url)
                            )
                            for artifact in update.removed
                        )

                    print("\n".join(message_lines), file=output)
            if fingerprint_updates:
                warnings.append(
                    "Detected fingerprint changes in the following locked {projects} for lock "
                    "generated by {platform}!\n{ids}".format(
                        platform=platform,
                        projects=pluralize(fingerprint_updates, "project"),
                        ids="\n".join(
                            "{project_name} {version}".format(
                                project_name=project_name, version=version
                            )
                            for project_name, version in fingerprint_updates.items()
                        ),
                    )
                )

        def process_req_edit(
            original,  # type: Optional[Requirement]
            final,  # type: Optional[Requirement]
        ):
            # type: (...) -> None
            if not original:
                print(
                    "  {lead_in} {requirement!r}".format(
                        lead_in="Would add" if dry_run else "Added",
                        requirement=str(final),
                    ),
                    file=output,
                )
            elif not final:
                print(
                    "  {lead_in} {requirement!r}".format(
                        lead_in="Would delete" if dry_run else "Deleted",
                        requirement=str(original),
                    ),
                    file=output,
                )
            else:
                print(
                    "  {lead_in} {original!r} to {final!r}".format(
                        lead_in="Would update" if dry_run else "Updated",
                        original=str(original),
                        final=str(final),
                    ),
                    file=output,
                )

        def process_req_edits(
            requirement_type,  # type: str
            original,  # type: Mapping[ProjectName, Requirement]
            final,  # type: Mapping[ProjectName, Requirement]
        ):
            # type: (...) -> Tuple[Tuple[Optional[Requirement], Optional[Requirement]], ...]
            edits = []  # type: List[Tuple[Optional[Requirement], Optional[Requirement]]]
            for name, original_req in original.items():
                final_req = final.get(name)
                if final_req != original_req:
                    edits.append((original_req, final_req))
            for name, final_req in final.items():
                if name not in original:
                    edits.append((None, final_req))
            if not edits:
                return ()

            print(
                "Updates to lock input {requirement_types}:".format(
                    requirement_types=pluralize(2, requirement_type)
                ),
                file=output,
            )
            for original_requirement, final_requirement in edits:
                process_req_edit(original=original_requirement, final=final_requirement)
            return tuple(edits)

        requirement_edits = process_req_edits(
            "requirement", original_requirements_by_project_name, requirements_by_project_name
        )
        constraints_edits = process_req_edits(
            "constraint", original_constraints_by_project_name, constraints_by_project_name
        )

        if not any((updates, requirement_edits, constraints_edits)):
            return Ok()

        if warnings:
            if self.options.fingerprint_mismatch in (
                FingerprintMismatch.WARN,
                FingerprintMismatch.ERROR,
            ):
                message = "\n".join(warnings)
                if self.options.fingerprint_mismatch is FingerprintMismatch.ERROR:
                    return Error(message)
                pex_warnings.warn(message)

        if dry_run:
            return Error() if dry_run is DryRunStyle.CHECK else Ok()

        with open(lock_file_path, "w") as fp:
            self._dump_lockfile(
                lock_file=attr.evolve(
                    lock_file,
                    pex_version=__version__,
                    requirements=SortedTuple(requirements_by_project_name.values(), key=str),
                    constraints=SortedTuple(constraints_by_project_name.values(), key=str),
                    locked_resolves=SortedTuple(
                        resolve_update.updated_resolve for resolve_update in lock_update.resolves
                    ),
                ),
                output=fp,
            )
        return Ok()
