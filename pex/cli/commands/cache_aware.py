# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
from datetime import datetime

from pex.cache import access as cache_access
from pex.common import pluralize
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO, Dict, List, Optional


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
        print("To get information on which processes these are, re-install Pex with the", file=out)
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


class CacheAwareMixin(object):
    @staticmethod
    def lock_cache_for_delete(out):
        # type: (IO[str]) -> bool

        try:
            with cache_access.await_delete_lock() as lock_file:
                _log_delete_start(lock_file, out)
                print(
                    "Attempting to acquire cache write lock (press CTRL-C to abort) ...",
                    file=out,
                )
        except KeyboardInterrupt:
            return False
        else:
            return True
