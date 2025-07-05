# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import os
import re
import signal
import subprocess
import sys
import time

from pex.common import safe_open
from pex.os import is_alive, kill
from pex.subprocess import launch_python_daemon
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


@attr.s(frozen=True)
class ServerInfo(object):
    url = attr.ib()  # type: str
    pid = attr.ib()  # type: int

    def __str__(self):
        # type: () -> str
        return "{url} @ {pid}".format(url=self.url, pid=self.pid)


@attr.s(frozen=True)
class Pidfile(object):
    @staticmethod
    def _pidfile(cache_dir):
        # type: (str) -> str
        return os.path.join(cache_dir, "pidfile")

    @classmethod
    def load(
        cls,
        server_name,  # type: str
        cache_dir,  # type: str
    ):
        # type: (...) -> Optional[Pidfile]
        pidfile = cls._pidfile(cache_dir)
        try:
            with open(pidfile) as fp:
                data = json.load(fp)
            return cls(ServerInfo(url=data["url"], pid=data["pid"]))
        except (OSError, IOError, ValueError, KeyError) as e:
            logger.debug(
                "Failed to load {server} pid file from {path}: {err}".format(
                    server=server_name, path=pidfile, err=e
                )
            )
            return None

    @staticmethod
    def _read_url(
        server_log,  # type: str
        timeout,  # type: float
    ):
        # type: (...) -> Optional[str]

        # The permutations of Python versions, simple http server module and the output it provides:
        #  2.7: Serving HTTP on 0.0.0.0 port 46399 ... -mSimpleHttpServer
        #  3.5: Serving HTTP on 0.0.0.0 port 45577 ... -mhttp.server
        # 3.6+: Serving HTTP on 0.0.0.0 port 33539 (http://0.0.0.0:33539/) ... -mhttp.server

        start = time.time()
        while time.time() - start < timeout:
            with open(server_log) as fp:
                for line in fp:
                    if line.endswith(("\r", "\n")):
                        match = re.search(r"Serving HTTP on \S+ port (?P<port>\d+)", line)
                        if match:
                            port = match.group("port")
                            return "http://localhost:{port}".format(port=port)
        return None

    @classmethod
    def record(
        cls,
        cache_dir,  # type: str
        server_log,  # type: str
        pid,  # type: int
        timeout=5.0,  # type: float
    ):
        # type: (...) -> Optional[Pidfile]
        url = cls._read_url(server_log, timeout)
        if not url:
            return None

        pidfile = cls._pidfile(cache_dir)
        with safe_open(pidfile, "w") as fp:
            json.dump(dict(url=url, pid=pid), fp, indent=2, sort_keys=True)
        return cls(ServerInfo(url=url, pid=pid))

    server_info = attr.ib()  # type: ServerInfo

    def alive(self):
        # type: () -> bool
        # TODO(John Sirois): Handle pid rollover
        return is_alive(self.server_info.pid)

    def kill(self):
        # type: () -> None
        os.kill(self.server_info.pid, signal.SIGTERM)


@attr.s(frozen=True)
class LaunchResult(object):
    server_info = attr.ib()  # type: ServerInfo
    already_running = attr.ib()  # type: bool


# Frozen exception types don't work under 3.11+ where the `__traceback__` attribute can be set
# after construction in some cases.
@attr.s
class LaunchError(Exception):
    """Indicates an error launching the server."""

    log = attr.ib()  # type: str
    additional_msg = attr.ib(default=None)  # type: Optional[str]
    verbose = attr.ib(default=False)  # type: bool

    def __str__(self):
        # type: () -> str
        lines = ["Error launching server."]
        if self.additional_msg:
            lines.append(self.additional_msg)
        if self.verbose:
            lines.append("Contents of the server log:")
            with open(self.log) as fp:
                lines.extend(fp.read().splitlines())
        else:
            lines.append("See the log at {log} for more details.".format(log=self.log))
        return "\n".join(lines)


@attr.s(frozen=True)
class Server(object):
    name = attr.ib()  # type: str
    cache_dir = attr.ib()  # type: str

    def pidfile(self):
        # type: () -> Optional[Pidfile]
        return Pidfile.load(self.name, self.cache_dir)

    def launch(
        self,
        document_root,  # type: str
        port=0,  # type: int
        timeout=5.0,  # type: float
        verbose_error=False,  # type: bool
    ):
        # type: (...) -> LaunchResult

        pidfile = self.pidfile()
        if pidfile and pidfile.alive():
            return LaunchResult(server_info=pidfile.server_info, already_running=True)

        # Not proper daemonization, but good enough.
        log = os.path.join(self.cache_dir, "log.txt")
        http_server_module = "http.server" if sys.version_info[0] == 3 else "SimpleHttpServer"
        env = os.environ.copy()
        # N.B.: We set up line buffering for the process pipes as well as the underlying Python running
        # the http server to ensure we can observe the `Serving HTTP on ...` line we need to grab the
        # ephemeral port chosen.
        env.update(PYTHONUNBUFFERED="1")
        with safe_open(log, "w") as fp:
            process = launch_python_daemon(
                args=[sys.executable, "-m", http_server_module, str(port)],
                env=env,
                cwd=document_root,
                bufsize=1,
                stdout=fp.fileno(),
                stderr=subprocess.STDOUT,
            )

        pidfile = Pidfile.record(
            cache_dir=self.cache_dir, server_log=log, pid=process.pid, timeout=timeout
        )
        if not pidfile:
            try:
                kill(process.pid)
            except OSError as e:
                raise LaunchError(
                    log,
                    additional_msg=(
                        "Also failed to kill the partially launched server at pid {pid}: "
                        "{err}".format(pid=process.pid, err=e)
                    ),
                    verbose=verbose_error,
                )
            raise LaunchError(log, verbose=verbose_error)
        return LaunchResult(server_info=pidfile.server_info, already_running=False)

    def shutdown(self):
        # type: () -> Optional[ServerInfo]

        pidfile = self.pidfile()
        if not pidfile or not pidfile.alive():
            return None

        logger.debug("Killing {server} {info}".format(server=self.name, info=pidfile.server_info))
        pidfile.kill()
        return pidfile.server_info
