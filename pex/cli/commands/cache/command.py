# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import re
from argparse import Action, ArgumentError, _ActionsContainer
from datetime import datetime, timedelta

from pex.cache import access as cache_access
from pex.cache import data as cache_data
from pex.cache.dirs import AtomicCacheDir, CacheDir, InstalledWheelDir, VenvDirs
from pex.cli.command import BuildTimeCommand
from pex.cli.commands.cache.bytes import ByteAmount, ByteUnits
from pex.cli.commands.cache.du import DiskUsage
from pex.commands.command import OutputMixin
from pex.common import pluralize, safe_rmtree
from pex.exceptions import reportable_unexpected_error_msg
from pex.jobs import iter_map_parallel, map_parallel
from pex.orderedset import OrderedSet
from pex.result import Error, Ok, Result
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

if TYPE_CHECKING:
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
            default=datetime.now() - timedelta(weeks=2),
            help=(
                "Prune zipapp and venv caches last accessed before the specified time. If the "
                "dependencies of the selected zipapps and venvs (e.g.: installed wheels) are "
                "unused by other zipapps and venvs, those dependencies are pruned as well. "
                "The cutoff time can be specified as a date in the format "
                "`<day number>/<month number>/<4 digit year>` or as a relative time in the format "
                "`<amount> [second(s)|minute(s)|hour(s)|day(s)|week(s)]"
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
        du = DiskUsage.collect(cache_dir.path)
        if not self.options.dry_run:
            safe_rmtree(cache_dir.path)
            if isinstance(cache_dir, InstalledWheelDir) and cache_dir.symlink_dir:
                safe_rmtree(cache_dir.symlink_dir)
            elif isinstance(cache_dir, VenvDirs):
                safe_rmtree(cache_dir.short_dir)
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

        cutoff = self.options.cutoff
        pex_dirs = list(cache_access.last_access_before(cutoff.cutoff))
        if not pex_dirs:
            print(
                "There are no cached PEX zipapps or venvs last accessed prior to {cutoff}".format(
                    cutoff=(
                        cutoff.spec
                        if cutoff.spec.endswith("ago") or cutoff.spec[-1].isdigit()
                        else "{cutoff} ago".format(cutoff=cutoff.spec)
                    ),
                ),
                file=fp,
            )
            return Ok()

        with cache_data.delete(pex_dirs, self.options.dry_run) as deps_iter:
            deps = list(deps_iter)

        print(
            "{pruned} {count} {cached_pex}".format(
                pruned="Would have pruned" if self.options.dry_run else "Pruned",
                count=len(pex_dirs),
                cached_pex=pluralize(pex_dirs, "cached PEX"),
            ),
            file=fp,
        )
        print(
            self._render_usage(
                list(
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
            print(
                "Might have pruned up to {count} {cached_pex_dependency}".format(
                    count=len(deps), cached_pex_dependency=pluralize(deps, "cached PEX dependency")
                ),
                file=fp,
            )
            print(
                self._render_usage(
                    list(
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
        else:
            with cache_data.prune(deps) as prunable_deps_iter:
                disk_usages = list(
                    iter_map_parallel(
                        prunable_deps_iter,
                        self._prune_cache_dir,
                        noun="cached PEX dependency",
                        verb="prune",
                        verb_past="pruned",
                    )
                )
                if not disk_usages:
                    print(
                        "No cached PEX dependencies were able to be pruned; all have un-pruned "
                        "cached PEX dependents.",
                        file=fp,
                    )
                elif len(deps) == 1:
                    print("Pruned the 1 cached PEX dependency.", file=fp)
                elif len(deps) == len(disk_usages):
                    print(
                        "Pruned all {count} cached PEX dependencies.".format(count=len(deps)),
                        file=fp,
                    )
                else:
                    print(
                        "Pruned {count} of {total} cached PEX dependencies.".format(
                            count=len(disk_usages), total=len(deps)
                        ),
                        file=fp,
                    )
                print(self._render_usage(disk_usages))
                print(file=fp)
        return Ok()
