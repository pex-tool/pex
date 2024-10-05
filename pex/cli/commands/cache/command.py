# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
from argparse import Action, ArgumentError, _ActionsContainer
from datetime import datetime

from pex.cache import access as cache_access
from pex.cache.dirs import CacheDir
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
                cache_dirs, self._purge_cache_dir, noun="entries", verb="purge", verb_past="purged"
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
