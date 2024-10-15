# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import re
from argparse import Action, ArgumentError, _ActionsContainer
from collections import Counter, OrderedDict
from datetime import datetime, timedelta

from pex.cache import access as cache_access
from pex.cache import data as cache_data
from pex.cache.dirs import (
    AtomicCacheDir,
    BootstrapDir,
    CacheDir,
    InstalledWheelDir,
    UnzipDir,
    VenvDirs,
)
from pex.cli.command import BuildTimeCommand
from pex.cli.commands.cache.bytes import ByteAmount, ByteUnits
from pex.cli.commands.cache.du import DiskUsage
from pex.commands.command import OutputMixin
from pex.common import pluralize, safe_rmtree
from pex.dist_metadata import ProjectNameAndVersion
from pex.exceptions import reportable_unexpected_error_msg
from pex.jobs import SpawnedJob, execute_parallel, iter_map_parallel, map_parallel
from pex.orderedset import OrderedSet
from pex.pip.installation import iter_all as iter_all_pips
from pex.pip.tool import Pip
from pex.pip.version import PipVersionValue
from pex.result import Error, Ok, Result
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
    import typing
    from typing import IO, Dict, Iterable, List, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class HandleAmountAction(Action):
    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = 0
        super(HandleAmountAction, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_str=None):
        if option_str in ("-H", "--human-readable"):
            amount_func = ByteAmount.human_readable
        elif option_str.startswith("--"):
            amount_func = ByteAmount.for_unit(ByteUnits.for_value(option_str[2:]))
        else:
            raise ArgumentError(
                argument=self,
                message=reportable_unexpected_error_msg(
                    "The HandleAmountAction was used in an unexpected place."
                ),
            )
        setattr(namespace, self.dest, amount_func)


@attr.s(frozen=True)
class Cutoff(object):
    @classmethod
    def parse(cls, spec):
        # type: (str) -> Cutoff
        match = re.match(
            r"(?P<amount>\d+)\s+(?P<unit>second|minute|hour|day|week)s?(\s+ago)?",
            spec.strip(),
            re.IGNORECASE,
        )
        if match:
            args = {match.group("unit") + "s": int(match.group("amount"))}
            cutoff = datetime.now() - timedelta(**args)
        else:
            cutoff = datetime.strptime(spec.strip(), "%d/%m/%Y")
        return cls(spec=spec, cutoff=cutoff)

    spec = attr.ib()  # type: str
    cutoff = attr.ib()  # type: datetime


class Cache(OutputMixin, BuildTimeCommand):
    """Interact with the Pex cache."""

    @staticmethod
    def _add_amount_argument(parser):
        # type: (_ActionsContainer) -> None

        parser.add_argument(
            "-H",
            "--human-readable",
            *["--{unit}".format(unit=unit.value) for unit in ByteUnits.values()],
            dest="amount_func",
            action=HandleAmountAction,
            default=ByteAmount.bytes,
            help=(
                "How to display disk usage amounts; defaults to bytes. The -H / --human-readable "
                "options display amounts in a human readable way and each of the other unit "
                "options displays amounts with that specified unit."
            )
        )

    @classmethod
    def _add_info_arguments(cls, parser):
        # type: (_ActionsContainer) -> None

        cls._add_amount_argument(parser)
        parser.add_argument(
            "-S",
            "--sort-size",
            dest="sort_by_size",
            action="store_true",
            help=(
                "Sort cache entry information by the total size of the cache entry. "
                "Entry information is sorted by entry name by default."
            ),
        )
        parser.add_argument(
            "-r",
            "--reverse",
            dest="reverse",
            action="store_true",
            help="Reverse the sorting of cache entry information.",
        )
        cls.add_output_option(parser, entity="Pex cache information")

    @staticmethod
    def _add_dry_run_option(parser):
        # type: (_ActionsContainer) -> None

        parser.add_argument(
            "-n",
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help=(
                "Don't actually purge cache entries; instead, perform a dry run that just prints "
                "out what actions would be taken"
            ),
        )

    @classmethod
    def _add_purge_arguments(cls, parser):
        # type: (_ActionsContainer) -> None

        cls._add_amount_argument(parser)
        parser.add_argument(
            "--entries",
            action="append",
            type=CacheDir.for_value,
            choices=[cache_dir for cache_dir in CacheDir.values() if cache_dir.can_purge],
            default=[],
            help=(
                "Specific cache entries to purge. By default, all entries are purged, but by "
                "specifying one or more particular --entries to purge, only those entries (and any "
                "other cache entries dependent on those) will be purged."
            ),
        )
        cls._add_dry_run_option(parser)
        cls.add_output_option(parser, entity="Pex purge results")

    @classmethod
    def _add_prune_arguments(cls, parser):
        # type: (_ActionsContainer) -> None

        cls._add_amount_argument(parser)
        parser.add_argument(
            "--older-than",
            dest="cutoff",
            type=Cutoff.parse,
            default=Cutoff.parse("2 weeks ago"),
            help=(
                "Prune zipapp and venv caches last accessed before the specified time. If the "
                "dependencies of the selected zipapps and venvs (e.g.: installed wheels) are "
                "unused by other zipapps and venvs, those dependencies are pruned as well. "
                "The cutoff time can be specified as a date in the format "
                "`<day number>/<month number>/<4 digit year>` or as a relative time in the format "
                "`<amount> [second(s)|minute(s)|hour(s)|day(s)|week(s)]`."
            ),
        )
        cls._add_dry_run_option(parser)
        cls.add_output_option(parser, entity="Pex purge results")

    @classmethod
    def add_extra_arguments(cls, parser):
        subcommands = cls.create_subcommands(
            parser,
            description="Interact with the Pex cache via the following subcommands.",
        )

        with subcommands.parser(
            name="dir",
            help="Print the current Pex cache directory path.",
            func=cls._dir,
            include_verbosity=False,
        ) as dir_parser:
            cls.add_output_option(dir_parser, entity="Pex cache directory")

        with subcommands.parser(
            name="info",
            help="Present information about Pex cache status.",
            func=cls._info,
            include_verbosity=False,
        ) as inspect_parser:
            cls._add_info_arguments(inspect_parser)

        with subcommands.parser(
            name="purge",
            help="Purge the Pex cache safely.",
            func=cls._purge,
            include_verbosity=False,
        ) as purge_parser:
            cls._add_purge_arguments(purge_parser)

        with subcommands.parser(
            name="prune",
            help="Prune the Pex cache safely.",
            func=cls._prune,
            include_verbosity=False,
        ) as prune_parser:
            cls._add_prune_arguments(prune_parser)

    def _dir(self):
        # type: () -> Result

        with self.output(self.options) as fp:
            print(ENV.PEX_ROOT, file=fp)

        return Ok()

    @staticmethod
    def _collect_info(cache_dir):
        # type: (CacheDir.Value) -> Tuple[CacheDir.Value, DiskUsage]
        return cache_dir, DiskUsage.collect(cache_dir.path())

    def _render_usage(self, disk_usage):
        # type: (Union[DiskUsage, Iterable[DiskUsage]]) -> str

        if isinstance(disk_usage, DiskUsage):
            du = disk_usage
            prefix = ""
        else:
            du = DiskUsage.aggregate(path=ENV.PEX_ROOT, usages=disk_usage)
            prefix = "Total: "

        return "{prefix}{size} in {subdir_count} {subdirs} and {file_count} {files}.".format(
            prefix=prefix,
            size=self.options.amount_func(du.size),
            subdir_count=du.subdirs,
            subdirs=pluralize(du.subdirs, "subdirectory"),
            file_count=du.files,
            files=pluralize(du.files, "file"),
        )

    def _info(self):
        # type: () -> Result

        with self.output(self.options) as fp:
            print("Path: {path}".format(path=ENV.PEX_ROOT), file=fp)
            print(file=fp)

            disk_usages = []  # type: List[DiskUsage]
            for cache_dir, disk_usage in sorted(
                map_parallel(
                    inputs=CacheDir.values(), function=self._collect_info, noun="cache directory"
                ),
                key=lambda info: (
                    (info[1].size, info[0].name) if self.options.sort_by_size else info[0].name
                ),
                reverse=self.options.reverse,
            ):
                disk_usages.append(disk_usage)
                print(
                    "{name}: {path}".format(name=cache_dir.name, path=cache_dir.rel_path), file=fp
                )
                print(cache_dir.description, file=fp)
                print(self._render_usage(disk_usage), file=fp)
                print(file=fp)
            print(self._render_usage(disk_usages), file=fp)
            print(file=fp)

        return Ok()

    def _purge_cache_dir(self, cache_dir):
        # type: (CacheDir.Value) -> Tuple[CacheDir.Value, DiskUsage]
        cache_dir_path = cache_dir.path()
        du = DiskUsage.collect(cache_dir_path)
        if not self.options.dry_run:
            safe_rmtree(cache_dir_path)
        return cache_dir, du

    @staticmethod
    def _log_delete_start(
        lock_file,  # type: str
        out,  # type: IO[str]
    ):
        # type: (...) -> None

        try:
            import psutil  # type: ignore[import]

            # N.B.: the `version_info` tuple was introduced in psutil 0.2.0.
            psutil_version = getattr(psutil, "version_info", None)
            if not psutil_version or psutil_version < (5, 3, 0):
                print(
                    "The psutil{version} module is available, but it is too old. "
                    "Need at least version 5.3.0.".format(
                        version=(
                            " {version}".format(version=".".join(map(str, psutil_version)))
                            if psutil_version
                            else ""
                        )
                    ),
                    file=out,
                )
                psutil = None
        except ImportError as e:
            print("Failed to import psutil:", e, file=out)
            psutil = None

        if not psutil:
            print("Will proceed with basic output.", file=out)
            print("---", file=out)
            print(
                "Note: this process will block until all other running Pex processes have exited.",
                file=out,
            )
            print(
                "To get information on which processes these are, re-install Pex with the", file=out
            )
            print("management extra; e.g.: with requirement pex[management]", file=out)
            print(file=out)
            return

        running = []  # type: List[psutil.Process]
        pid = os.getpid()  # type: int
        for process in psutil.process_iter(
            ["pid", "open_files", "username", "create_time", "environ", "cmdline"]
        ):
            if pid == process.info["pid"]:
                continue
            if any(lock_file == of.path for of in process.info["open_files"] or ()):
                running.append(process)

        if running:
            print(
                "Waiting on {count} in flight {processes} (with shared lock on {lock_file}) to "
                "complete before deleting:".format(
                    count=len(running), processes=pluralize(running, "process"), lock_file=lock_file
                ),
                file=out,
            )
            print("---", file=out)
            for index, process in enumerate(running, start=1):
                print(
                    "{index}. pid {pid} started by {username} at {create_time}".format(
                        index=index,
                        pid=process.info["pid"],
                        username=process.info["username"],
                        create_time=datetime.fromtimestamp(process.info["create_time"]).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    ),
                    file=out,
                )

                pex_env = process.info["environ"]  # type: Optional[Dict[str, str]]
                if pex_env:
                    pex_env = {k: v for k, v in pex_env.items() if k.startswith("PEX")}
                if pex_env:
                    print("   Pex env: {pex_env}".format(pex_env=pex_env), file=out)

                cmdline = process.info["cmdline"]
                if cmdline:
                    print("   cmdline: {cmdline}".format(cmdline=cmdline), file=out)
            print(file=out)

    def _purge(self):
        # type: () -> Result

        with self.output(self.options) as fp:
            cache_dirs = OrderedSet()  # type: OrderedSet[CacheDir.Value]
            if self.options.entries:
                cache_dirs.update(self.options.entries)
                print(
                    "{purging} requested entries from {pex_root}: {cache_dirs}".format(
                        purging="Would purge" if self.options.dry_run else "Purging",
                        pex_root=ENV.PEX_ROOT,
                        cache_dirs=", ".join(cache_dir.rel_path for cache_dir in cache_dirs),
                    ),
                    file=fp,
                )

                dependents = OrderedSet()  # type: OrderedSet[CacheDir.Value]
                for cache_dir in cache_dirs:
                    dependents.update(cache_dir.iter_transitive_dependents())
                if dependents:
                    print(
                        "{purging} those entries transitive dependents in: {dependents}".format(
                            purging="Would also purge" if self.options.dry_run else "Also purging",
                            dependents=", ".join(dep.rel_path for dep in dependents),
                        ),
                        file=fp,
                    )
                    cache_dirs.update(dependents)
            else:
                print(
                    "{purging} all cache entries from {pex_root}:".format(
                        purging="Would purge" if self.options.dry_run else "Purging",
                        pex_root=ENV.PEX_ROOT,
                    ),
                    file=fp,
                )
                cache_dirs.update(CacheDir.values())
            print(file=fp)

            if not self.options.dry_run:
                try:
                    with cache_access.await_delete_lock() as lock_file:
                        self._log_delete_start(lock_file, out=fp)
                        print(
                            "Attempting to acquire cache write lock (press CTRL-C to abort) ...",
                            file=fp,
                        )
                except KeyboardInterrupt:
                    return Error("No cache entries purged.")
                finally:
                    print(file=fp)

            disk_usages = []  # type: List[DiskUsage]
            for cache_dir, du in iter_map_parallel(
                cache_dirs, self._purge_cache_dir, noun="entry", verb="purge", verb_past="purged"
            ):
                print(
                    "{purged} cache {name} from {rel_path}".format(
                        purged="Would have purged" if self.options.dry_run else "Purged",
                        name=cache_dir.name,
                        rel_path=cache_dir.rel_path,
                    ),
                    file=fp,
                )
                disk_usages.append(du)
                print(self._render_usage(du), file=fp)
                print(file=fp)
            if disk_usages:
                print(self._render_usage(disk_usages), file=fp)
                print(file=fp)

        return Ok()

    def _prune_cache_dir(self, cache_dir):
        # type: (AtomicCacheDir) -> DiskUsage
        paths_to_prune = []  # type: List[str]

        def prune_if_exists(path):
            if os.path.exists(path):
                paths_to_prune.append(path)

        if isinstance(cache_dir, InstalledWheelDir):
            paths_to_prune.append(os.path.dirname(cache_dir.path))
            packed_wheel_dir = CacheDir.PACKED_WHEELS.path(cache_dir.install_hash)
            prune_if_exists(packed_wheel_dir)
        elif isinstance(cache_dir, BootstrapDir):
            paths_to_prune.append(cache_dir.path)
            prune_if_exists(CacheDir.BOOTSTRAP_ZIPS.path(cache_dir.bootstrap_hash))
        else:
            paths_to_prune.append(cache_dir.path)

        disk_usages = [DiskUsage.collect(path) for path in paths_to_prune]
        if not self.options.dry_run:
            for path in paths_to_prune:
                safe_rmtree(path)
            if isinstance(cache_dir, InstalledWheelDir) and cache_dir.symlink_dir:
                safe_rmtree(cache_dir.symlink_dir)
            elif isinstance(cache_dir, VenvDirs):
                safe_rmtree(cache_dir.short_dir)

        return (
            disk_usages[0]
            if len(disk_usages) == 1
            else DiskUsage.aggregate(cache_dir.path, disk_usages)
        )

    def _prune_pip(self, pip_info):
        # type: (Tuple[Pip, bool]) -> DiskUsage
        pip, prune_version = pip_info
        path_to_prune = pip.pex_dir.base_dir if prune_version else pip.pex_dir.path
        du = DiskUsage.collect(path_to_prune)
        if not self.options.dry_run:
            safe_rmtree(path_to_prune)
        return du

    def _prune(self):
        # type: () -> Result

        with self.output(self.options) as fp:
            if not self.options.dry_run:
                try:
                    with cache_access.await_delete_lock() as lock_file:
                        self._log_delete_start(lock_file, out=fp)
                        print(
                            "Attempting to acquire cache write lock (press CTRL-C to abort) ...",
                            file=fp,
                        )
                except KeyboardInterrupt:
                    return Error("No cache entries purged.")
                finally:
                    print(file=fp)

        def prune_unused_deps(additional=False):
            # type: (bool) -> Iterable[InstalledWheelDir]
            with cache_data.prune(tuple(InstalledWheelDir.iter_all())) as unused_deps_iter:
                unused_wheels = tuple(
                    dep for dep in unused_deps_iter if isinstance(dep, InstalledWheelDir)
                )
                disk_usages = tuple(
                    iter_map_parallel(
                        unused_wheels,
                        self._prune_cache_dir,
                        noun="cached PEX dependency",
                        verb="prune",
                        verb_past="pruned",
                    )
                )
                if disk_usages:
                    print(
                        "Pruned {count} {additional}unused PEX {dependencies}.".format(
                            count=len(disk_usages),
                            additional="additional " if additional else "",
                            dependencies=pluralize(disk_usages, "dependency"),
                        ),
                        file=fp,
                    )
                    print(self._render_usage(disk_usages))
                    print(file=fp)
                return unused_wheels

        cutoff = self.options.cutoff
        pex_dirs = OrderedDict(
            cache_access.last_access_before(cutoff.cutoff)
        )  # type: OrderedDict[Union[UnzipDir, VenvDirs], float]
        pex_hashes_to_prune = set(pex_dir.pex_hash for pex_dir in pex_dirs)
        last_access_by_pex_hash = {
            pex_dir.pex_hash: last_access for pex_dir, last_access in pex_dirs.items()
        }

        # True to prune the Pip version completely, False to just prune the Pip PEX.
        pips_to_prune = OrderedDict()  # type: OrderedDict[Pip, bool]
        # N.B.: We just need 1 Pip per version (really per paired cache). Whether a Pip has
        # extra requirements installed does not affect cache management.
        pip_caches_to_prune = OrderedDict()  # type: OrderedDict[PipVersionValue, Pip]
        for pip in iter_all_pips():
            if pip.pex_hash in pex_hashes_to_prune:
                pips_to_prune[pip] = False
            else:
                pip_caches_to_prune[pip.version] = pip
        for pip in pips_to_prune:
            if pip.version not in pip_caches_to_prune:
                pips_to_prune[pip] = True

        def prune_pips():
            # type: () -> None
            if not pips_to_prune:
                return

            print(
                "{pruned} {count} {cached_pex}.".format(
                    pruned="Would have pruned" if self.options.dry_run else "Pruned",
                    count=len(pips_to_prune),
                    cached_pex=pluralize(pips_to_prune, "Pip PEX"),
                ),
                file=fp,
            )
            print(
                self._render_usage(
                    tuple(
                        iter_map_parallel(
                            pips_to_prune.items(),
                            function=self._prune_pip,
                            noun="Pip",
                            verb="prune",
                            verb_past="pruned",
                        )
                    )
                ),
                file=fp,
            )

        def prune_pip_caches(wheels):
            # type: (Iterable[InstalledWheelDir]) -> None

            prunable_wheels = set()
            for wheel in wheels:
                prunable_pnav = ProjectNameAndVersion.from_filename(wheel.wheel_name)
                prunable_wheels.add(
                    (prunable_pnav.canonicalized_project_name, prunable_pnav.canonicalized_version)
                )
            if not prunable_wheels:
                return

            def spawn_list(pip):
                # type: (Pip) -> SpawnedJob[Tuple[ProjectNameAndVersion, ...]]
                return SpawnedJob.stdout(
                    job=pip.spawn_cache_list(),
                    result_func=lambda stdout: tuple(
                        ProjectNameAndVersion.from_filename(wheel_file)
                        for wheel_file in stdout.decode("utf-8").splitlines()
                        if wheel_file
                    ),
                )

            pip_removes = []  # type: List[Tuple[Pip, str]]
            for pip, project_name_and_versions in zip(
                pip_caches_to_prune.values(),
                execute_parallel(inputs=pip_caches_to_prune.values(), spawn_func=spawn_list),
            ):
                for pnav in project_name_and_versions:
                    if (
                        pnav.canonicalized_project_name,
                        pnav.canonicalized_version,
                    ) in prunable_wheels:
                        pip_removes.append(
                            (
                                pip,
                                "{project_name}-{version}*".format(
                                    project_name=pnav.project_name, version=pnav.version
                                ),
                            )
                        )

            def parse_remove(stdout):
                # type: (bytes) -> int

                # The output from `pip cache remove` is a line like:
                # Files removed: 42
                _, sep, count = stdout.decode("utf-8").partition(":")
                if sep != ":" or not count:
                    return 0
                try:
                    return int(count)
                except ValueError:
                    return 0

            def spawn_remove(args):
                # type: (Tuple[Pip, str]) -> SpawnedJob[int]
                pip, wheel_name_glob = args
                return SpawnedJob.stdout(
                    job=pip.spawn_cache_remove(wheel_name_glob), result_func=parse_remove
                )

            removes_by_pip = Counter()  # type: typing.Counter[str]
            for pip, remove_count in zip(
                [pip for pip, _ in pip_removes],
                execute_parallel(inputs=pip_removes, spawn_func=spawn_remove),
            ):
                removes_by_pip[pip.version.value] += remove_count
                cache_access.record_access(
                    pip.pex_dir, last_access=last_access_by_pex_hash[pip.pex_hash]
                )
            if removes_by_pip:
                total = sum(removes_by_pip.values())
                print(
                    "Pruned {total} cached {wheels} from {count} Pip {version}:".format(
                        total=total,
                        wheels=pluralize(total, "wheel"),
                        count=len(removes_by_pip),
                        version=pluralize(removes_by_pip, "version"),
                    ),
                    file=fp,
                )
                for pip_version, remove_count in sorted(removes_by_pip.items()):
                    print(
                        "Pip {version}: removed {remove_count} {wheels}".format(
                            version=pip_version,
                            remove_count=remove_count,
                            wheels=pluralize(remove_count, "wheel"),
                        ),
                        file=fp,
                    )

        if not pex_dirs:
            print(
                "There are no cached PEX zipapps or venvs last accessed prior to {cutoff}.".format(
                    cutoff=(
                        cutoff.spec
                        if cutoff.spec.endswith("ago") or cutoff.spec[-1].isdigit()
                        else "{cutoff} ago".format(cutoff=cutoff.spec)
                    ),
                ),
                file=fp,
            )
            print(file=fp)
            unused_wheels = prune_unused_deps()
            prune_pip_caches(unused_wheels)
            prune_pips()
            return Ok()

        print(
            "{pruned} {count} {cached_pex}.".format(
                pruned="Would have pruned" if self.options.dry_run else "Pruned",
                count=len(pex_dirs),
                cached_pex=pluralize(pex_dirs, "cached PEX"),
            ),
            file=fp,
        )
        print(
            self._render_usage(
                tuple(
                    iter_map_parallel(
                        pex_dirs,
                        self._prune_cache_dir,
                        noun="cached PEX",
                        verb="prune",
                        verb_past="pruned",
                    )
                )
            ),
            file=fp,
        )
        print(file=fp)

        if self.options.dry_run:
            deps = tuple(cache_data.dir_dependencies(pex_dirs))
            print(
                "Might have pruned up to {count} {cached_pex_dependency}.".format(
                    count=len(deps), cached_pex_dependency=pluralize(deps, "cached PEX dependency")
                ),
                file=fp,
            )
            print(
                self._render_usage(
                    tuple(
                        iter_map_parallel(
                            deps,
                            self._prune_cache_dir,
                            noun="cached PEX dependency",
                            verb="prune",
                            verb_past="pruned",
                        )
                    )
                )
            )
            print(file=fp)
            prune_pips()
        else:
            with cache_data.delete(pex_dirs) as deps_iter:
                deps = tuple(deps_iter)
            with cache_data.prune(deps) as prunable_deps_iter:
                unused_deps = tuple(prunable_deps_iter)
                unused_wheels = OrderedSet(
                    dep for dep in unused_deps if isinstance(dep, InstalledWheelDir)
                )
                disk_usages = tuple(
                    iter_map_parallel(
                        unused_deps,
                        self._prune_cache_dir,
                        noun="cached PEX dependency",
                        verb="prune",
                        verb_past="pruned",
                    )
                )
                if deps and not disk_usages:
                    print(
                        "No cached PEX dependencies were able to be pruned; all have un-pruned "
                        "cached PEX dependents.",
                        file=fp,
                    )
                elif len(deps) == 1:
                    print("Pruned the 1 cached PEX dependency.", file=fp)
                elif len(deps) > 1 and len(deps) == len(disk_usages):
                    print(
                        "Pruned all {count} cached PEX dependencies.".format(count=len(deps)),
                        file=fp,
                    )
                elif len(deps) > 1:
                    print(
                        "Pruned {count} of {total} cached PEX dependencies.".format(
                            count=len(disk_usages), total=len(deps)
                        ),
                        file=fp,
                    )
                if disk_usages:
                    print(self._render_usage(disk_usages))
                if deps or disk_usages:
                    print(file=fp)
            unused_wheels.update(prune_unused_deps(additional=len(disk_usages) > 0))
            prune_pip_caches(unused_wheels)
            prune_pips()
        return Ok()
