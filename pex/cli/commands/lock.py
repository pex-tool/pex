# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import functools
import itertools
import os.path
import sys
from argparse import Action, ArgumentError, ArgumentParser, ArgumentTypeError, _ActionsContainer
from collections import OrderedDict, deque
from multiprocessing.pool import ThreadPool
from operator import attrgetter

from pex import dependency_configuration, pex_warnings
from pex.argparse import HandleBoolAction
from pex.build_system import pep_517
from pex.cli.command import BuildTimeCommand
from pex.commands.command import JsonMixin, OutputMixin
from pex.common import pluralize, safe_delete, safe_mkdtemp, safe_open
from pex.compatibility import commonpath, shlex_quote
from pex.dependency_configuration import DependencyConfiguration
from pex.dist_metadata import (
    Constraint,
    Distribution,
    MetadataType,
    ProjectNameAndVersion,
    Requirement,
    RequirementParseError,
)
from pex.enum import Enum
from pex.exceptions import production_assert
from pex.executables import is_exe
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pep_376 import InstalledWheel, Record
from pex.pep_427 import InstallableType
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pip.version import PipVersionValue
from pex.requirements import LocalProjectRequirement
from pex.resolve import project, requirement_options, resolver_options, target_options
from pex.resolve.config import finalize as finalize_resolve_config
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.lock_resolver import resolve_from_lock
from pex.resolve.locked_resolve import (
    LocalProjectArtifact,
    LockConfiguration,
    LockedResolve,
    LockStyle,
    Resolved,
    TargetSystem,
    VCSArtifact,
)
from pex.resolve.lockfile import json_codec, requires_dist
from pex.resolve.lockfile.create import create
from pex.resolve.lockfile.model import Lockfile
from pex.resolve.lockfile.subset import subset
from pex.resolve.lockfile.updater import (
    ArtifactsUpdate,
    ArtifactUpdate,
    DeleteUpdate,
    FingerprintUpdate,
    LockUpdate,
    LockUpdater,
    ResolveUpdateRequest,
    VersionUpdate,
)
from pex.resolve.path_mappings import PathMappings
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolved_requirement import Fingerprint, Pin
from pex.resolve.resolver_configuration import LockRepositoryConfiguration, PipConfiguration
from pex.resolve.resolver_options import parse_lockfile
from pex.resolve.resolvers import Resolver
from pex.resolve.script_metadata import ScriptMetadataApplication, apply_script_metadata
from pex.resolve.target_configuration import InterpreterConstraintsNotSatisfied, TargetConfiguration
from pex.result import Error, Ok, Result, try_
from pex.sorted_tuple import SortedTuple
from pex.targets import LocalInterpreter, Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import InvalidVirtualenvError, Virtualenv
from pex.version import __version__

if TYPE_CHECKING:
    from typing import IO, Dict, Iterable, List, Mapping, Optional, Set, Text, Tuple, Union

    import attr  # vendor:skip

    from pex.resolve.lockfile.updater import Update
else:
    from pex.third_party import attr


class FingerprintMismatch(Enum["FingerprintMismatch.Value"]):
    class Value(Enum.Value):
        pass

    IGNORE = Value("ignore")
    WARN = Value("warn")
    ERROR = Value("error")


FingerprintMismatch.seal()


class ExportFormat(Enum["ExportFormat.Value"]):
    class Value(Enum.Value):
        pass

    PIP = Value("pip")
    PIP_NO_HASHES = Value("pip-no-hashes")
    PEP_665 = Value("pep-665")


ExportFormat.seal()


class ExportSortBy(Enum["ExportSortBy.Value"]):
    class Value(Enum.Value):
        pass

    SPECIFICITY = Value("specificity")
    PROJECT_NAME = Value("project-name")


ExportSortBy.seal()


class DryRunStyle(Enum["DryRunStyle.Value"]):
    class Value(Enum.Value):
        pass

    DISPLAY = Value("display")
    CHECK = Value("check")


DryRunStyle.seal()


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


@attr.s(frozen=True)
class SyncTarget(object):
    _PIP_PROJECT_NAME = ProjectName("pip")

    @classmethod
    def resolve_command(
        cls,
        venv,  # type: Virtualenv
        command=None,  # type: Optional[Tuple[str, ...]]
    ):
        # type: (...) -> SyncTarget
        if command:
            argv0 = command[0] if os.path.isabs(command[0]) else venv.bin_path(command[0])
            command = (argv0,) + command[1:]
        return SyncTarget(venv=venv, command=command)

    @classmethod
    def resolve_venv(
        cls,
        argv0,  # type str
        *additional_args  # type: str
    ):
        # type: (...) -> Union[SyncTarget, Error]

        argv0_path = None  # type: Optional[str]
        if is_exe(argv0):
            argv0_path = argv0
        else:
            path = os.environ.get("PATH")
            if path:
                for entry in path.split(os.pathsep):
                    exe_path = os.path.abspath(os.path.join(entry, argv0))
                    if is_exe(exe_path):
                        argv0_path = exe_path
                        break

        if argv0_path:
            venv = Virtualenv.enclosing(python=argv0_path)
            if not venv:
                try:
                    venv = Virtualenv(os.path.dirname(os.path.dirname(argv0_path)))
                except InvalidVirtualenvError as e:
                    return Error(
                        "Could not find a valid venv enclosing {argv0} to sync: {err}.\n"
                        "Try explicitly specifying a venv to sync with `--venv`.".format(
                            err=e, argv0=argv0
                        )
                    )
            command = [argv0_path]
            command.extend(additional_args)
            return SyncTarget(venv=venv, command=tuple(command))

        if os.path.isdir(argv0) and not additional_args:
            try:
                return SyncTarget(venv=Virtualenv(argv0))
            except InvalidVirtualenvError as e:
                return Error(
                    "The directory at {path} is not a valid venv to sync: {err}.\n"
                    "Try explicitly specifying a venv to sync with `--venv`.".format(
                        err=e, path=argv0
                    )
                )

        return Error(
            "Could not determine a venv to sync after examining {argv0}.\n"
            "Try explicitly specifying a venv to sync with `--venv`.".format(argv0=argv0)
        )

    venv = attr.ib()  # type: Virtualenv
    command = attr.ib(default=None)  # type: Optional[Tuple[str, ...]]

    def sync(
        self,
        distributions,  # type: Iterable[Distribution]
        confirm=True,  # type: bool
        retain_pip=False,  # type: bool
    ):
        # type: (...) -> Result

        abs_venv_dir = os.path.realpath(self.venv.venv_dir)

        existing_distributions_by_project_name = {
            dist.metadata.project_name: dist for dist in self.venv.iter_distributions()
        }  # type: Dict[ProjectName, Distribution]
        installed_pip = existing_distributions_by_project_name.get(
            self._PIP_PROJECT_NAME
        )  # type: Optional[Distribution]

        resolved_pip = None  # type: Optional[Distribution]
        to_remove = []  # type: List[Distribution]
        to_install = []  # type: List[Distribution]
        for distribution in distributions:
            if self._PIP_PROJECT_NAME == distribution.metadata.project_name:
                resolved_pip = distribution
            existing_distribution = existing_distributions_by_project_name.pop(
                distribution.metadata.project_name, None
            )
            if not existing_distribution:
                to_install.append(distribution)
            elif existing_distribution.metadata.version != distribution.metadata.version:
                to_remove.append(existing_distribution)
                to_install.append(distribution)
        if retain_pip:
            existing_distributions_by_project_name.pop(self._PIP_PROJECT_NAME, None)
        to_remove.extend(existing_distributions_by_project_name.values())

        to_unlink_by_pin = (
            OrderedDict()
        )  # type: OrderedDict[Tuple[ProjectName, Version], List[Text]]
        for distribution in to_remove:
            to_unlink = []  # type: List[Text]
            if distribution.metadata.type is MetadataType.DIST_INFO:
                to_unlink.extend(
                    os.path.realpath(os.path.join(distribution.location, installed_file.path))
                    for installed_file in Record.read(distribution.iter_metadata_lines("RECORD"))
                )
            elif distribution.metadata.type is MetadataType.EGG_INFO:
                installed_files = distribution.metadata.files.metadata_file_rel_path(
                    "installed-files.txt"
                )
                if installed_files:
                    base_dir = os.path.realpath(
                        os.path.join(distribution.location, os.path.dirname(installed_files))
                    )
                    to_unlink.extend(
                        os.path.join(base_dir, path)
                        for path in distribution.iter_metadata_lines("installed-files.txt")
                    )
                    # Pip generates "installed-files.txt" upon installing and this file does not
                    # include itself; so we tack that on here ourselves.
                    to_unlink.append(
                        os.path.realpath(os.path.join(distribution.location, installed_files))
                    )
            if to_unlink:
                to_unlink_by_pin[
                    (distribution.metadata.project_name, distribution.metadata.version)
                ] = [file for file in to_unlink if abs_venv_dir == commonpath((abs_venv_dir, file))]
        if confirm and to_unlink_by_pin:
            for (project_name, version), files in to_unlink_by_pin.items():
                print(project_name, version, ":", file=sys.stderr)
                for f in files:
                    print("    ", f, file=sys.stderr)
            if input(
                "Remove the outdated distributions listed above from the venv at "
                "{venv}? [yN]: ".format(venv=self.venv.venv_dir)
            ).strip().lower() not in ("y", "yes"):
                return Error("Sync cancelled.")

        if to_unlink_by_pin:
            parent_dirs = set()  # type: Set[Text]
            for file in itertools.chain.from_iterable(to_unlink_by_pin.values()):
                safe_delete(file)
                parent_dirs.add(os.path.dirname(file))
            for parent_dir in sorted(parent_dirs, reverse=True):
                if not os.listdir(parent_dir) and abs_venv_dir == commonpath(
                    (abs_venv_dir, parent_dir)
                ):
                    os.rmdir(parent_dir)

        if retain_pip and not resolved_pip and not installed_pip:
            self.venv.ensure_pip(upgrade=True)

        if to_install:
            for distribution in to_install:
                for src, dst in InstalledWheel.load(distribution.location).reinstall_venv(
                    self.venv
                ):
                    TRACER.log("Installed {src} -> {dst}".format(src=src, dst=dst))
            for script in self.venv.rewrite_scripts():
                TRACER.log("Re-wrote script shebang for {script}".format(script=script))

        if self.command:
            try:
                os.execv(self.command[0], self.command)
            except OSError as e:
                return Error("Failed to execute {exe}: {err}".format(exe=self.command[0], err=e))

        return Ok()


@attr.s(frozen=True)
class LockUpdateRequest(object):
    targets = attr.ib()  # type: Targets
    _lock_file_path = attr.ib()  # type: str
    _lock_updater = attr.ib()  # type: LockUpdater
    _update_requests = attr.ib()  # type: Iterable[ResolveUpdateRequest]

    def update(
        self,
        updates=(),  # type: Iterable[Requirement]
        replacements=(),  # type: Iterable[Requirement]
        deletes=(),  # type: Iterable[ProjectName]
        artifacts_can_change=False,  # type: bool
    ):
        # type: (...) -> Union[LockUpdate, Result]
        if not self._update_requests:
            return self._no_updates()

        return self._lock_updater.update(
            update_requests=self._update_requests,
            updates=updates,
            replacements=replacements,
            deletes=deletes,
            artifacts_can_change=artifacts_can_change,
        )

    def sync(self, requirement_configuration):
        # type: (RequirementConfiguration) -> Union[LockUpdate, Result]
        if not self._update_requests:
            return self._no_updates()

        return self._lock_updater.sync(
            update_requests=self._update_requests,
            requirement_configuration=requirement_configuration,
        )

    def _no_updates(self):
        # type: () -> Ok
        return Ok(
            "No lock update was performed.\n"
            "The following platforms present in {lock_file} were not found on the local "
            "machine:\n"
            "{missing_platforms}\n"
            "You might still be able to update the lock by adjusting target options like "
            "--python-path.".format(
                lock_file=self._lock_file_path,
                missing_platforms="\n".join(
                    sorted(
                        "+ {platform}".format(platform=locked_resolve.platform_tag)
                        for locked_resolve in self._lock_updater.lock_file.locked_resolves
                    )
                ),
            )
        )


@attr.s(frozen=True)
class LockingConfiguration(object):
    requirement_configuration = attr.ib()  # type: RequirementConfiguration
    target_configuration = attr.ib()  # type: TargetConfiguration
    lock_configuration = attr.ib()  # type: LockConfiguration
    script_metadata_application = attr.ib(default=None)  # type: Optional[ScriptMetadataApplication]

    def check_scripts(self, targets):
        # type: (Targets) -> Optional[Error]

        if self.script_metadata_application is None:
            return None

        errors = []  # type: List[str]
        for target in targets.unique_targets():
            scripts = self.script_metadata_application.target_does_not_apply(target)
            if scripts:
                errors.append(
                    "{target} is not compatible with {count} {scripts}:\n"
                    "{script_incompatibilities}".format(
                        target=target.render_description(),
                        count=len(scripts),
                        scripts=pluralize(scripts, "script"),
                        script_incompatibilities="\n".join(
                            "   + {source} requires Python '{requires_python}'".format(
                                source=script.source,
                                requires_python=script.requires_python,
                            )
                            for script in scripts
                        ),
                    )
                )
        if errors:
            return Error(
                "PEP-723 scripts were specified that are incompatible with {count} lock "
                "{targets}:\n{errors}".format(
                    count=len(errors),
                    targets=pluralize(errors, "target"),
                    errors="\n".join(
                        "{index}. {error}".format(index=index, error=error)
                        for index, error in enumerate(errors, start=1)
                    ),
                )
            )

        return None


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
        options_group = parser.add_argument_group(
            title="Requirement options",
            description="Indicate which distributions should be resolved",
        )
        options_group.add_argument(
            "--exe",
            "--script",
            dest="scripts",
            default=[],
            action="append",
            help=(
                "Specify scripts with PEP-723 metadata to gather requirements and interpreter "
                "constraints from as lock inputs."
            ),
        )
        requirement_options.register(options_group)
        project.register_options(
            options_group,
            project_help=(
                "Add the transitive dependencies of the local project at the specified path to "
                "the lock but do not lock project itself."
            ),
        )
        dependency_configuration.register(options_group)
        cls._add_target_options(parser)
        resolver_options.register(
            cls._create_resolver_options_group(parser),
            include_pex_repository=False,
            include_lock=False,
            include_pre_resolved=False,
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
        cls.add_create_lock_options(create_parser)
        cls.add_output_option(create_parser, entity="lock")

    @classmethod
    def add_create_lock_options(cls, create_parser):
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
        create_parser.add_argument(
            "--elide-unused-requires-dist",
            "--no-elide-unused-requires-dist",
            dest="elide_unused_requires_dist",
            type=bool,
            default=False,
            action=HandleBoolAction,
            help=(
                "When creating the lock, elide dependencies from the 'requires_dists' lists that "
                "can never be active due to markers. This does not change the reachable content of "
                "the lock, but it does cut down on lock file size. This currently only elides "
                "extras deps that are never activated, but may trim more in the future."
            ),
        )
        cls._add_lock_options(create_parser)
        cls._add_resolve_options(create_parser)
        cls.add_json_options(create_parser, entity="lock", include_switch=False)

    @classmethod
    def _add_subset_arguments(cls, subset_parser):
        # type: (_ActionsContainer) -> None

        # N.B.: Needed to handle the case of local project requirements as lock subset input, these
        # will need to resolve and run a PEP-517 build system to produce an sdist to grab project
        # name metadata from.
        cls._add_resolve_options(subset_parser)

        cls._add_lockfile_option(subset_parser, verb="subset", positional=False)
        cls._add_lock_options(subset_parser)
        cls.add_output_option(subset_parser, entity="lock subset")
        cls.add_json_options(subset_parser, entity="lock subset", include_switch=False)

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
                "The format to export the lock to. Currently only the Pip requirements file "
                "formats (using `--hash` or bare) are supported."
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
        resolver_options.register(
            resolver_options_parser,
            include_pex_repository=False,
            include_lock=False,
            include_pre_resolved=False,
        )

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
        cls.add_update_lock_options(update_parser)
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
        cls._add_lockfile_option(update_parser, verb="update")
        cls._add_lock_options(update_parser)
        cls.add_json_options(update_parser, entity="lock", include_switch=False)
        cls._add_target_options(update_parser)
        resolver_options_parser = cls._create_resolver_options_group(update_parser)
        resolver_options.register(
            resolver_options_parser,
            include_pex_repository=False,
            include_lock=False,
            include_pre_resolved=False,
        )

    @classmethod
    def add_update_lock_options(
        cls,
        update_parser,  # type: _ActionsContainer
        include_strict=True,  # type: bool
    ):
        if include_strict:
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

    @classmethod
    def _add_sync_arguments(cls, sync_parser):
        # type: (_ActionsContainer) -> None
        sync_parser.add_argument(
            "--venv",
            help=(
                "Synchronize this venv to the contents of the lock after synchronizing the "
                "contents of the lock to the passed requirements."
            ),
        )
        sync_parser.add_argument(
            "--venv-python",
            help="Use this interpreter to create the `--venv` if the venv doesn't exist.",
        )
        sync_parser.add_argument(
            "--pip",
            "--retain-pip",
            "--no-pip",
            "--no-retain-pip",
            action=HandleBoolAction,
            default=False,
            help=(
                "When syncing a venv in the default `--no-pip`/`--no-retain-pip` mode, new venvs "
                "will be created without Pip installed in them and existing venvs will have Pip "
                "removed unless the lock being synced specifies a locked Pip, in which case that "
                "locked Pip version will be ensured. When syncing a venv in the "
                "`--pip`/`--retain-pip` mode, new venvs will be created with Pip installed in them "
                "and existing venvs will have Pip installed. The version of Pip installed will be "
                "taken from the lock being synced is present, and will be the latest compatible "
                "with the venv interpreter otherwise."
            ),
        )
        sync_parser.add_argument(
            "-y",
            "--yes",
            default=False,
            action="store_true",
            help=(
                "Do not prompt when deleting or overwriting venv distributions during a venv sync."
            ),
        )
        cls._add_lockfile_option(sync_parser, verb="sync", positional=False)
        cls.add_create_lock_options(sync_parser)
        cls.add_update_lock_options(sync_parser, include_strict=False)

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
            name="subset", help="Subset a lock file.", func=cls._subset
        ) as subset_parser:
            cls._add_subset_arguments(subset_parser)
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
        with subcommands.parser(
            name="sync",
            help=(
                "Create or update a Pex lock file from requirements and optionally synchronize a "
                "venv to it."
            ),
            passthrough_args=(
                "The path to a venv directory to sync with this lock or else a command line whose "
                "1st argument resolves to a binary in a venv."
            ),
            func=cls._sync,
        ) as sync_parser:
            cls._add_sync_arguments(sync_parser)

    def _resolve_targets(
        self,
        action,  # type: str
        style,  # type: LockStyle.Value
        target_configuration=None,  # type: Optional[TargetConfiguration]
    ):
        # type: (...) -> Union[Targets, Error]

        target_config = target_configuration or target_options.configure(
            self.options,
            pip_configuration=resolver_options.create_pip_configuration(
                self.options, use_system_time=False
            ),
        )
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
        )

    def _merge_project_requirements(
        self,
        requirement_configuration,  # type: RequirementConfiguration
        pip_configuration,  # type: PipConfiguration
        targets,  # type: Targets
    ):
        # type: (...) -> RequirementConfiguration
        group_requirements = project.get_group_requirements(self.options)
        projects = project.get_projects(self.options)
        if not projects and not group_requirements:
            return requirement_configuration

        requirements = OrderedSet(requirement_configuration.requirements)
        requirements.update(str(req) for req in group_requirements)
        if projects:
            with TRACER.timed(
                "Collecting requirements from {count} local {projects}".format(
                    count=len(projects), projects=pluralize(projects, "project")
                )
            ):
                requirements.update(
                    str(req)
                    for req in projects.collect_requirements(
                        resolver=ConfiguredResolver(pip_configuration),
                        interpreter=targets.interpreter,
                        pip_version=pip_configuration.version,
                        max_jobs=pip_configuration.max_jobs,
                    )
                )
        return attr.evolve(requirement_configuration, requirements=requirements)

    def _locking_configuration(self, pip_configuration):
        # type: (PipConfiguration) -> Union[LockingConfiguration, Error]
        requirement_configuration = requirement_options.configure(self.options)
        target_configuration = target_options.configure(
            self.options, pip_configuration=pip_configuration
        )
        script_metadata_application = None  # type: Optional[ScriptMetadataApplication]
        if self.options.scripts:
            script_metadata_application = apply_script_metadata(
                self.options.scripts, requirement_configuration, target_configuration
            )
            requirement_configuration = script_metadata_application.requirement_configuration
            target_configuration = script_metadata_application.target_configuration
        if self.options.style == LockStyle.UNIVERSAL:
            lock_configuration = LockConfiguration(
                style=LockStyle.UNIVERSAL,
                requires_python=tuple(
                    str(interpreter_constraint.requires_python)
                    for interpreter_constraint in target_configuration.interpreter_constraints
                ),
                target_systems=tuple(self.options.target_systems),
                elide_unused_requires_dist=self.options.elide_unused_requires_dist,
            )
        elif self.options.target_systems:
            return Error(
                "The --target-system option only applies to --style {universal} locks.".format(
                    universal=LockStyle.UNIVERSAL.value
                )
            )
        else:
            lock_configuration = LockConfiguration(
                style=self.options.style,
                elide_unused_requires_dist=self.options.elide_unused_requires_dist,
            )
        return LockingConfiguration(
            requirement_configuration,
            target_configuration,
            lock_configuration,
            script_metadata_application=script_metadata_application,
        )

    def _create(self):
        # type: () -> Result

        pip_configuration = resolver_options.create_pip_configuration(
            self.options, use_system_time=False
        )
        locking_configuration = try_(self._locking_configuration(pip_configuration))
        targets = try_(
            self._resolve_targets(
                action="creating",
                style=self.options.style,
                target_configuration=locking_configuration.target_configuration,
            )
        )
        try_(locking_configuration.check_scripts(targets))
        pip_configuration = try_(
            finalize_resolve_config(
                resolver_configuration=pip_configuration,
                targets=targets,
                context="lock creation",
            )
        )
        requirement_configuration = self._merge_project_requirements(
            locking_configuration.requirement_configuration, pip_configuration, targets
        )
        dependency_config = dependency_configuration.configure(self.options)
        self._dump_lockfile(
            try_(
                create(
                    lock_configuration=locking_configuration.lock_configuration,
                    requirement_configuration=requirement_configuration,
                    targets=targets,
                    pip_configuration=pip_configuration,
                    dependency_configuration=dependency_config,
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
        supported_formats = ExportFormat.PIP, ExportFormat.PIP_NO_HASHES
        if self.options.format not in supported_formats:
            return Error(
                "Only the Pip lock formats are supported currently. "
                "Choose one of: {choices}".format(choices=" or ".join(map(str, supported_formats)))
            )

        lockfile_path, lock_file = self._load_lockfile()
        pip_configuration = resolver_options.create_pip_configuration(
            self.options, use_system_time=False
        )
        targets = target_options.configure(
            self.options, pip_configuration=pip_configuration
        ).resolve_targets()
        target = targets.require_unique_target(
            purpose="exporting a lock in the {pip!r} format".format(pip=ExportFormat.PIP)
        )

        with TRACER.timed("Selecting locks for {target}".format(target=target)):
            subset_result = try_(
                subset(
                    targets=targets,
                    lock=lock_file,
                    requirement_configuration=requirement_configuration,
                    network_configuration=pip_configuration.network_configuration,
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

        requirement_by_pin = {}  # type: Dict[Pin, str]
        fingerprints_by_pin = OrderedDict()  # type: OrderedDict[Pin, List[Fingerprint]]
        warnings = []  # type: List[str]

        def add_warning(
            type_,  # type: str
            requirement,  # type: str
        ):
            # type: (...) -> str
            warnings.append("{type} {requirement!r}".format(type=type_, requirement=requirement))
            return requirement

        for downloaded_artifact in resolved.downloadable_artifacts:
            if isinstance(downloaded_artifact.artifact, LocalProjectArtifact):
                requirement_by_pin[downloaded_artifact.pin] = add_warning(
                    "local project requirement",
                    requirement="{project_name} @ file://{directory}".format(
                        project_name=downloaded_artifact.pin.project_name,
                        directory=downloaded_artifact.artifact.directory,
                    ),
                )
            elif isinstance(downloaded_artifact.artifact, VCSArtifact):
                requirement_by_pin[downloaded_artifact.pin] = add_warning(
                    "VCS requirement",
                    requirement=downloaded_artifact.artifact.as_unparsed_requirement(
                        downloaded_artifact.pin.project_name
                    ),
                )
            else:
                requirement_by_pin[downloaded_artifact.pin] = "{project_name}=={version}".format(
                    project_name=downloaded_artifact.pin.project_name,
                    version=downloaded_artifact.pin.version.raw,
                )
            fingerprints_by_pin.setdefault(downloaded_artifact.pin, []).append(
                downloaded_artifact.artifact.fingerprint
            )

        if self.options.format is ExportFormat.PIP and warnings:
            print(
                "The requirements exported from {lockfile} include the following requirements\n"
                "that tools likely won't support --hash for:\n"
                "{warnings}\n"
                "\n"
                "If you can accept a lack of hash checking you can specify "
                "`--format pip-no-hashes`.\n".format(
                    lockfile=lockfile_path,
                    warnings="\n".join(
                        "+ {warning}".format(warning=warning) for warning in warnings
                    ),
                ),
                file=sys.stderr,
            )
        with self.output(self.options) as output:
            pins = fingerprints_by_pin.keys()  # type: Iterable[Pin]
            if self.options.sort_by == ExportSortBy.PROJECT_NAME:
                pins = sorted(pins, key=attrgetter("project_name.normalized"))
            for pin in pins:
                requirement = requirement_by_pin[pin]
                if self.options.format is ExportFormat.PIP_NO_HASHES:
                    print(requirement, file=output)
                else:
                    fingerprints = fingerprints_by_pin[pin]
                    output.write(
                        "{requirement} \\\n"
                        "  {hashes}\n".format(
                            requirement=requirement,
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
        # type: () -> Result
        requirement_configuration = requirement_options.configure(self.options)
        return self._export(requirement_configuration=requirement_configuration)

    def _build_sdist(
        self,
        local_project_requirement,  # type: LocalProjectRequirement
        target,  # type: Target
        resolver,  # type: Resolver
        pip_version=None,  # type: Optional[PipVersionValue]
    ):
        # type: (...) -> Union[str, Error]
        return pep_517.build_sdist(
            local_project_requirement.path,
            dist_dir=safe_mkdtemp(),
            target=target,
            resolver=resolver,
            pip_version=pip_version,
        )

    def _build_sdists(
        self,
        target,  # type: Target
        pip_configuration,  # type: PipConfiguration
        local_project_requirements,  # type: Iterable[LocalProjectRequirement]
    ):
        # type: (...) -> Iterable[Tuple[LocalProjectRequirement, Union[str, Error]]]

        func = functools.partial(
            self._build_sdist,
            target=target,
            resolver=ConfiguredResolver(pip_configuration),
            pip_version=pip_configuration.version,
        )
        pool = ThreadPool(processes=pip_configuration.max_jobs)
        try:
            return zip(local_project_requirements, pool.map(func, local_project_requirements))
        finally:
            pool.close()
            pool.join()

    def _process_local_project_requirements(
        self,
        target,  # type: Target
        pip_configuration,  # type: PipConfiguration
        local_project_requirements,  # type: Iterable[LocalProjectRequirement]
    ):
        # type: (...) -> Union[Mapping[LocalProjectRequirement, Requirement], Error]

        errors = []  # type: List[str]
        requirement_by_local_project_requirement = (
            {}
        )  # type: Dict[LocalProjectRequirement, Requirement]
        for lpr, sdist_or_error in self._build_sdists(
            target, pip_configuration, local_project_requirements
        ):
            if isinstance(sdist_or_error, Error):
                errors.append("{project}: {err}".format(project=lpr.path, err=sdist_or_error))
            else:
                requirement_by_local_project_requirement[lpr] = lpr.as_requirement(sdist_or_error)
        if errors:
            return Error(
                "Failed to determine the names and version of {count} local project input "
                "{requirements} to the lock subset:\n{errors}".format(
                    count=len(errors),
                    requirements=pluralize(errors, "requirement"),
                    errors="\n".join(
                        "{index}. {error}".format(index=index, error=error)
                        for index, error in enumerate(errors, start=1)
                    ),
                )
            )
        return requirement_by_local_project_requirement

    def _subset(self):
        # type: () -> Result

        lockfile_path, lock_file = self._load_lockfile()

        pip_configuration = resolver_options.create_pip_configuration(
            self.options, use_system_time=False
        )
        target_configuration = target_options.configure(
            self.options, pip_configuration=pip_configuration
        )
        requirement_configuration = requirement_options.configure(self.options)
        script_metadata_application = None  # type: Optional[ScriptMetadataApplication]
        if self.options.scripts:
            script_metadata_application = apply_script_metadata(
                self.options.scripts, requirement_configuration, target_configuration
            )
            requirement_configuration = script_metadata_application.requirement_configuration
            target_configuration = script_metadata_application.target_configuration
        locking_configuration = LockingConfiguration(
            requirement_configuration,
            target_configuration=target_configuration,
            lock_configuration=lock_file.lock_configuration(),
            script_metadata_application=script_metadata_application,
        )
        targets = try_(
            self._resolve_targets(
                action="creating",
                style=lock_file.style,
                target_configuration=locking_configuration.target_configuration,
            )
        )
        try_(locking_configuration.check_scripts(targets))
        pip_configuration = try_(
            finalize_resolve_config(
                resolver_configuration=pip_configuration,
                targets=targets,
                context="lock creation",
            )
        )
        requirement_configuration = self._merge_project_requirements(
            locking_configuration.requirement_configuration, pip_configuration, targets
        )

        network_configuration = resolver_options.create_network_configuration(self.options)
        parsed_requirements = requirement_configuration.parse_requirements(
            network_configuration=network_configuration
        )

        # This target is used to build an sdist for each local project in the lock input
        # requirements in order to extract the project name from the local project metadata.
        # The project will need to be compatible with all targets in the lock; so any target should
        # do.
        representative_target = targets.unique_targets().pop(last=False)
        local_project_requirements = try_(
            self._process_local_project_requirements(
                target=representative_target,
                pip_configuration=pip_configuration,
                local_project_requirements=[
                    req for req in parsed_requirements if isinstance(req, LocalProjectRequirement)
                ],
            )
        )
        root_requirements = {
            (
                local_project_requirements[req]
                if isinstance(req, LocalProjectRequirement)
                else req.requirement
            )
            for req in parsed_requirements
        }

        constraint_by_project_name = OrderedDict(
            (constraint.requirement.project_name, constraint.requirement.as_constraint())
            for constraint in requirement_configuration.parse_constraints(
                network_configuration=network_configuration
            )
        )

        resolve_subsets = []  # type: List[LockedResolve]
        for locked_resolve in lock_file.locked_resolves:
            available = {
                locked_req.pin.project_name: (
                    ProjectNameAndVersion(
                        locked_req.pin.project_name.raw, locked_req.pin.version.raw
                    ),
                    locked_req,
                )
                for locked_req in locked_resolve.locked_requirements
            }
            retain = set()
            to_resolve = deque(root_requirements)
            while to_resolve:
                req = to_resolve.popleft()
                if req.project_name in retain:
                    continue
                retain.add(req.project_name)
                dep = available.get(req.project_name)
                if not dep:
                    return Error(
                        "There is no lock entry for {project} in {lock_file} to satisfy the "
                        "{transitive}'{req}' requirement.".format(
                            project=req.project_name,
                            lock_file=lockfile_path,
                            transitive="" if req in root_requirements else "transitive ",
                            req=req,
                        )
                    )
                elif dep:
                    pnav, locked_req = dep
                    if pnav not in req:
                        production_assert(
                            req in root_requirements,
                            "Transitive requirements in a lock should always match existing lock "
                            "entries. Found {project} {version} in {lock_file}, which does not "
                            "satisfy transitive requirement '{req}' found in the same lock.".format(
                                project=pnav.project_name,
                                version=pnav.version,
                                lock_file=lockfile_path,
                                req=req,
                            ),
                        )
                        return Error(
                            "The locked version of {project} in {lock_file} is {version} which "
                            "does not satisfy the '{req}' requirement.".format(
                                project=pnav.project_name,
                                lock_file=lockfile_path,
                                version=pnav.version,
                                req=req,
                            )
                        )
                    elif (
                        req.project_name in constraint_by_project_name
                        and pnav not in constraint_by_project_name[req.project_name]
                    ):
                        return Error(
                            "The locked version of {project} in {lock_file} is {version} which "
                            "does not satisfy the '{constraint}' constraint.".format(
                                project=pnav.project_name,
                                lock_file=lockfile_path,
                                version=pnav.version,
                                constraint=constraint_by_project_name[req.project_name],
                            )
                        )
                    to_resolve.extend(requires_dist.filter_dependencies(req, locked_req))

            resolve_subsets.append(
                attr.evolve(
                    locked_resolve,
                    locked_requirements=SortedTuple(
                        locked_requirement
                        for locked_requirement in locked_resolve.locked_requirements
                        if locked_requirement.pin.project_name in retain
                    ),
                )
            )

        self._dump_lockfile(
            attr.evolve(
                lock_file,
                locked_resolves=SortedTuple(resolve_subsets),
                constraints=(
                    SortedTuple(constraint_by_project_name.values(), key=str)
                    if constraint_by_project_name
                    else lock_file.constraints
                ),
                requirements=SortedTuple(root_requirements, key=str),
            )
        )
        return Ok()

    def _create_lock_update_request(
        self,
        lock_file_path,  # type: str
        lock_file,  # type: Lockfile
        dependency_config=DependencyConfiguration(),  # type: DependencyConfiguration
    ):
        # type: (...) -> Union[LockUpdateRequest, Error]

        pip_configuration = resolver_options.create_pip_configuration(
            self.options, use_system_time=False
        )
        lock_updater = LockUpdater.create(
            lock_file=lock_file,
            repos_configuration=pip_configuration.repos_configuration,
            network_configuration=pip_configuration.network_configuration,
            max_jobs=pip_configuration.max_jobs,
            use_pip_config=pip_configuration.use_pip_config,
            dependency_configuration=dependency_config,
            pip_log=resolver_options.get_pip_log(self.options),
        )

        target_configuration = target_options.configure(
            self.options, pip_configuration=pip_configuration
        )
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
            locked_resolve_count = len(lock_file.locked_resolves)
            if lock_file.style is LockStyle.UNIVERSAL and locked_resolve_count != 1:
                return Error(
                    "The lock at {path} contains {count} locked resolves; so it "
                    "cannot be updated as a universal lock which requires exactly one locked "
                    "resolve.".format(path=lock_file_path, count=locked_resolve_count)
                )
            if locked_resolve_count == 1:
                locked_resolve = lock_file.locked_resolves[0]
                update_targets = (
                    [LocalInterpreter.create(targets.interpreter)]
                    if lock_file.style is LockStyle.UNIVERSAL
                    else targets.unique_targets()
                )
                update_requests = [
                    ResolveUpdateRequest(target=target, locked_resolve=locked_resolve)
                    for target in update_targets
                ]
            else:
                # N.B.: With 1 locked resolve in the lock file we're updating, there is no ambiguity
                # about which locked resolve should be paired with which target, but when there is
                # more than 1 locked resolve, we need to match up targets with the locked resolve
                # they should be responsible for updating. Here we use the existing subset logic
                # which is stricter than necessary in the sync case since it takes into account
                # artifacts. For any locked resolve with locked requirements that only have platform
                # specific wheel artifacts, this can prevent an update of a locked resolve to a new
                # Python version or platform.
                #
                # TODO(John Sirois): Consider implementing more permissive locked resolve selection
                #   logic to support syncing lock files containing multiple locked resolves:
                #     https://github.com/pex-tool/pex/issues/2386

                subset_result = try_(
                    subset(
                        targets=targets,
                        lock=lock_file,
                        network_configuration=pip_configuration.network_configuration,
                        build_configuration=lock_file.build_configuration(),
                        transitive=lock_file.transitive,
                    )
                )
                update_requests = [
                    ResolveUpdateRequest(
                        target=resolved_subset.target,
                        locked_resolve=resolved_subset.resolved.source,
                    )
                    for resolved_subset in subset_result.subsets
                ]
        if getattr(self.options, "strict", False) and lock_file.style is not LockStyle.UNIVERSAL:
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

        return LockUpdateRequest(targets, lock_file_path, lock_updater, update_requests)

    def _process_lock_update(
        self,
        lock_update,  # type: LockUpdate
        lock_file,  # type: Lockfile
        lock_file_path,  # type: str
    ):
        # type: (...) -> Result

        original_requirements_by_project_name = OrderedDict(
            (requirement.project_name, requirement) for requirement in lock_file.requirements
        )
        requirements_by_project_name = OrderedDict(
            (requirement.project_name, requirement) for requirement in lock_update.requirements
        )

        original_constraints_by_project_name = OrderedDict(
            (constraint.project_name, constraint) for constraint in lock_file.constraints
        )
        constraints_by_project_name = original_constraints_by_project_name.copy()

        dry_run = self.options.dry_run
        path_mappings = self._get_path_mappings()
        output = sys.stdout if dry_run is DryRunStyle.DISPLAY else sys.stderr
        updates = []  # type: List[Update]
        warnings = []  # type: List[str]
        for resolve_update in lock_update.resolves:
            platform = resolve_update.updated_resolve.target_platform
            if not resolve_update.updates:
                print(
                    "No updates for lock generated by {platform}.".format(platform=platform),
                    file=output,
                )
                continue

            print(
                "Updates for lock generated by {platform}:".format(platform=platform), file=output
            )
            fingerprint_updates = OrderedDict()  # type: OrderedDict[ProjectName, Version]
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
                        "{requirements}",
                        project_name=project_name,
                        requirements="\n".join(map(str, requirements_by_project_name.values())),
                    )
                    constraints_by_project_name.pop(project_name, None)
                elif isinstance(update, VersionUpdate):
                    update_req = lock_update.update_requirements_by_project_name.get(project_name)
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
                            constraints_by_project_name[project_name] = update_req.as_constraint()
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
                elif isinstance(update, ArtifactsUpdate):
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
                else:
                    message_lines = [
                        "  {lead_in} {project_name} {version} requirements:".format(
                            lead_in="Would update" if dry_run else "Updated",
                            project_name=project_name,
                            version=update.version,
                        )
                    ]
                    if update.added:
                        message_lines.extend(
                            "    + {added}".format(added=req) for req in update.added
                        )
                    if update.removed:
                        message_lines.extend(
                            "    - {removed}".format(removed=req) for req in update.removed
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
            original,  # type: Optional[Constraint]
            final,  # type: Optional[Constraint]
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
            original,  # type: Mapping[ProjectName, Constraint]
            final,  # type: Mapping[ProjectName, Constraint]
        ):
            # type: (...) -> Tuple[Tuple[Optional[Constraint], Optional[Constraint]], ...]
            edits = []  # type: List[Tuple[Optional[Constraint], Optional[Constraint]]]
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

    def _update(self):
        # type: () -> Result

        pin = getattr(self.options, "pin", False)
        if pin and any(
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

        update_requirements = []  # type: List[Requirement]
        for project in self.options.update_projects:
            try:
                update_requirements.append(Requirement.parse(project))
            except RequirementParseError as e:
                return Error(
                    "Failed to parse project requirement to update {project!r}: {err}".format(
                        project=project, err=e
                    )
                )

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
        lock_update_request = try_(
            self._create_lock_update_request(lock_file_path=lock_file_path, lock_file=lock_file)
        )
        lock_update = lock_update_request.update(
            updates=update_requirements,
            replacements=replace_requirements,
            deletes=delete_projects,
            artifacts_can_change=pin,
        )
        if isinstance(lock_update, Result):
            return lock_update

        return self._process_lock_update(lock_update, lock_file, lock_file_path)

    def _sync(self):
        # type: () -> Result

        resolver_configuration = cast(
            LockRepositoryConfiguration,
            resolver_options.configure(self.options, use_system_time=False),
        )
        production_assert(isinstance(resolver_configuration, LockRepositoryConfiguration))
        pip_configuration = resolver_configuration.pip_configuration
        locking_configuration = try_(self._locking_configuration(pip_configuration))
        dependency_config = dependency_configuration.configure(self.options)
        lock_file_path = self.options.lock
        if os.path.exists(lock_file_path):
            lock_configuration = locking_configuration.lock_configuration
            build_configuration = pip_configuration.build_configuration
            original_lock_file = try_(parse_lockfile(self.options, lock_file_path=lock_file_path))
            lock_file = attr.evolve(
                original_lock_file,
                style=lock_configuration.style,
                requires_python=SortedTuple(lock_configuration.requires_python),
                target_systems=SortedTuple(lock_configuration.target_systems),
                elide_unused_requires_dist=lock_configuration.elide_unused_requires_dist,
                pip_version=pip_configuration.version,
                resolver_version=pip_configuration.resolver_version,
                allow_prereleases=pip_configuration.allow_prereleases,
                allow_wheels=build_configuration.allow_wheels,
                only_wheels=SortedTuple(build_configuration.only_wheels),
                allow_builds=build_configuration.allow_builds,
                only_builds=SortedTuple(build_configuration.only_builds),
                prefer_older_binary=build_configuration.prefer_older_binary,
                use_pep517=build_configuration.use_pep517,
                build_isolation=build_configuration.build_isolation,
                transitive=pip_configuration.transitive,
                excluded=SortedTuple(dependency_config.excluded),
                overridden=SortedTuple(dependency_config.all_overrides()),
            )
            lock_update_request = try_(
                self._create_lock_update_request(
                    lock_file_path=lock_file_path,
                    lock_file=lock_file,
                    dependency_config=dependency_config,
                )
            )
            try_(locking_configuration.check_scripts(lock_update_request.targets))
            pip_configuration = try_(
                finalize_resolve_config(
                    resolver_configuration=pip_configuration,
                    targets=lock_update_request.targets,
                    context="lock syncing",
                )
            )
            requirement_configuration = self._merge_project_requirements(
                locking_configuration.requirement_configuration,
                pip_configuration,
                lock_update_request.targets,
            )
            lock_update = lock_update_request.sync(
                requirement_configuration=requirement_configuration,
            )
            if isinstance(lock_update, Result):
                return lock_update

            try_(self._process_lock_update(lock_update, lock_file, lock_file_path))
        else:
            targets = try_(
                self._resolve_targets(
                    action="creating",
                    style=self.options.style,
                    target_configuration=locking_configuration.target_configuration,
                )
            )
            try_(locking_configuration.check_scripts(targets))
            pip_configuration = try_(
                finalize_resolve_config(
                    resolver_configuration=pip_configuration,
                    targets=targets,
                    context="lock creation",
                )
            )
            requirement_configuration = self._merge_project_requirements(
                locking_configuration.requirement_configuration, pip_configuration, targets
            )
            lockfile = try_(
                create(
                    lock_configuration=locking_configuration.lock_configuration,
                    requirement_configuration=requirement_configuration,
                    targets=targets,
                    pip_configuration=pip_configuration,
                    dependency_configuration=dependency_config,
                )
            )
            if self.options.dry_run:
                output = sys.stdout if self.options.dry_run is DryRunStyle.DISPLAY else sys.stderr
                for locked_resolve in lockfile.locked_resolves:
                    print(
                        "Would lock {count} {project} for platform {platform}:".format(
                            count=len(locked_resolve.locked_requirements),
                            project=pluralize(locked_resolve.locked_requirements, "project"),
                            platform=locked_resolve.target_platform,
                        ),
                        file=output,
                    )
                    for locked_requirement in locked_resolve.locked_requirements:
                        print(
                            "  {project_name} {version}".format(
                                project_name=locked_requirement.pin.project_name,
                                version=locked_requirement.pin.version,
                            ),
                            file=output,
                        )
            else:
                with safe_open(lock_file_path, "w") as fp:
                    self._dump_lockfile(lockfile, output=fp)

        sync_target = None  # type: Optional[SyncTarget]
        if self.options.venv:
            if os.path.exists(self.options.venv):
                try:
                    venv = Virtualenv(self.options.venv)
                except InvalidVirtualenvError as e:
                    return Error("The given --venv is not a valid venv: {err}".format(err=e))
            else:
                if self.options.venv_python:
                    interpreter = (
                        PythonInterpreter.from_binary(self.options.venv_python)
                        if os.path.isfile(self.options.venv_python)
                        else PythonInterpreter.from_env(self.options.venv_python)
                    )
                else:
                    targets = target_options.configure(
                        self.options, pip_configuration=pip_configuration
                    ).resolve_targets()
                    interpreters = [
                        target.get_interpreter()
                        for target in targets.unique_targets()
                        if isinstance(target, LocalInterpreter)
                    ]
                    if len(interpreters) != 1:
                        return Error(
                            "In order to create the venv {venv} the sync operation needs to know "
                            "which interpreter to use to create it.\n"
                            "Use `--venv-interpreter` to select an interpreter for venv creation."
                        )
                    interpreter = interpreters[0]
                venv = Virtualenv.create(self.options.venv, interpreter=interpreter)
            sync_target = SyncTarget.resolve_command(venv=venv, command=self.passthrough_args)
        elif self.passthrough_args:
            sync_target = try_(
                SyncTarget.resolve_venv(self.passthrough_args[0], *self.passthrough_args[1:])
            )
        if not sync_target:
            return Ok()

        if self.options.dry_run:
            would_update_venv_msg = "Would sync venv at {venv}".format(
                venv=sync_target.venv.venv_dir
            )
            if sync_target.command:
                return Ok(
                    os.linesep.join(
                        (
                            would_update_venv_msg + " and run the following command in it:",
                            "  " + " ".join(shlex_quote(arg) for arg in sync_target.command),
                        )
                    )
                )
            else:
                return Ok(would_update_venv_msg + ".")

        lock_file = try_(parse_lockfile(self.options, lock_file_path=lock_file_path))
        target = LocalInterpreter.create(sync_target.venv.interpreter)
        resolve_result = try_(
            resolve_from_lock(
                targets=Targets.from_target(target),
                lock=lock_file,
                resolver=ConfiguredResolver(pip_configuration),
                requirements=requirement_configuration.requirements,
                requirement_files=requirement_configuration.requirement_files,
                constraint_files=requirement_configuration.constraint_files,
                indexes=pip_configuration.repos_configuration.indexes,
                find_links=pip_configuration.repos_configuration.find_links,
                resolver_version=pip_configuration.resolver_version,
                network_configuration=pip_configuration.network_configuration,
                password_entries=pip_configuration.repos_configuration.password_entries,
                build_configuration=pip_configuration.build_configuration,
                transitive=pip_configuration.transitive,
                max_parallel_jobs=pip_configuration.max_jobs,
                pip_version=pip_configuration.version,
                use_pip_config=pip_configuration.use_pip_config,
                extra_pip_requirements=pip_configuration.extra_requirements,
                keyring_provider=pip_configuration.keyring_provider,
                result_type=InstallableType.INSTALLED_WHEEL_CHROOT,
            )
        )
        return sync_target.sync(
            distributions=[
                resolved_distribution.distribution
                for resolved_distribution in resolve_result.distributions
                if resolved_distribution.target == target
            ],
            confirm=not self.options.yes,
            retain_pip=self.options.pip,
        )
